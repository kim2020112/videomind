import { ref, computed } from 'vue'
import { useAuth } from './useAuth.js'

const API_BASE = '/api'

export function useTaskPoller() {
  const { getAuthHeaders } = useAuth()
  const activeTasks = ref([])
  const activeTaskCount = computed(() => activeTasks.value.length)
  let pollTimer = null

  async function pollOnce() {
    try {
      const res = await fetch(`${API_BASE}/tasks/active`, { headers: getAuthHeaders() })
      if (res.ok) {
        const data = await res.json()
        const newTasks = data.tasks || []
        // 去重：内容相同时不替换引用，避免触发下游组件无意义重渲染
        const oldIds = activeTasks.value.map(t => `${t.task_id}:${t.status}:${t.stage}`).join(',')
        const newIds = newTasks.map(t => `${t.task_id}:${t.status}:${t.stage}`).join(',')
        if (oldIds !== newIds) {
          activeTasks.value = newTasks
        }
      }
    } catch {
      // 静默失败，下次轮询重试
    }
  }

  function startPolling() {
    if (pollTimer) return
    pollOnce() // 立即执行一次
    pollTimer = setInterval(pollOnce, 10000)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  return {
    activeTasks,
    activeTaskCount,
    startPolling,
    stopPolling,
    pollOnce,
  }
}
