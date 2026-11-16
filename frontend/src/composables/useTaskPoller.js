import { ref, computed, getCurrentScope, onScopeDispose } from 'vue'
import { useAuth } from './useAuth.js'

const API_BASE = '/api'

export function useTaskPoller() {
  const { getAuthHeaders } = useAuth()
  const activeTasks = ref([])
  const activeTaskCount = computed(() => activeTasks.value.length)
  let pollTimer = null
  let polling = false
  let generation = 0
  let inFlight = null
  let controller = null
  let failures = 0

  function pollOnce() {
    if (inFlight) return inFlight
    const ticket = generation
    controller = new AbortController()
    const signal = controller.signal
    const requestController = controller
    const pending = Promise.resolve().then(() => run(ticket, signal, requestController))
    inFlight = pending
    return pending
  }

  async function run(ticket, signal, requestController) {
    const timeout = setTimeout(() => requestController.abort(), 15000)
    try {
      const res = await fetch(`${API_BASE}/tasks/active`, { headers: getAuthHeaders(), signal })
      if (res.ok) {
        const data = await res.json()
        if (ticket !== generation) return
        failures = 0
        const newTasks = data.tasks || []
        // 去重：内容相同时不替换引用，避免触发下游组件无意义重渲染
        const signature = task => [
          task.task_id,
          task.status,
          task.stage,
          task.progress,
          task.message,
          task.queue_position,
          task.error,
        ].join(':')
        const oldIds = activeTasks.value.map(signature).join(',')
        const newIds = newTasks.map(signature).join(',')
        if (oldIds !== newIds) {
          activeTasks.value = newTasks
        }
      } else if (res.status === 401 || res.status === 403) {
        if (ticket === generation) { activeTasks.value = []; stopPolling() }
      } else if (ticket === generation) {
        failures += 1
      }
    } catch {
      if (ticket === generation) failures += 1
    } finally {
      clearTimeout(timeout)
      if (ticket !== generation) return
      inFlight = null
      controller = null
      if (polling) {
        clearTimeout(pollTimer)
        pollTimer = setTimeout(pollOnce, Math.min(60000, (activeTasks.value.length > 0 ? 5000 : 15000) * 2 ** Math.min(failures, 3)))
      }
    }
  }

  function startPolling() {
    if (polling) return
    polling = true
    pollOnce()
  }

  function stopPolling() {
    polling = false
    generation += 1
    controller?.abort()
    controller = null
    inFlight = null
    clearTimeout(pollTimer)
    pollTimer = null
  }

  if (getCurrentScope()) onScopeDispose(stopPolling)

  return {
    activeTasks,
    activeTaskCount,
    startPolling,
    stopPolling,
    pollOnce,
  }
}
