import { ref, computed } from 'vue'
import { useAuth } from './useAuth.js'

const API_BASE = '/api'

export function useTaskPoller() {
  const { getAuthHeaders } = useAuth()
  const activeTasks = ref([])
  const activeTaskCount = computed(() => activeTasks.value.length)
  let pollTimer = null
  let polling = false

  async function pollOnce() {
    try {
      const res = await fetch(`${API_BASE}/tasks/active`, { headers: getAuthHeaders() })
      if (res.ok) {
        const data = await res.json()
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
      }
    } catch {
      // 静默失败，下次轮询重试
    } finally {
      if (polling) {
        clearTimeout(pollTimer)
        pollTimer = setTimeout(pollOnce, activeTasks.value.length > 0 ? 5000 : 15000)
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
    clearTimeout(pollTimer)
    pollTimer = null
  }

  return {
    activeTasks,
    activeTaskCount,
    startPolling,
    stopPolling,
    pollOnce,
  }
}
