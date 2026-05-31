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
        activeTasks.value = data.tasks || []
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
