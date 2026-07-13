import { ref, readonly } from 'vue'

const API_BASE = '/api'

// 全局单例状态
const safeCapabilities = () => ({
  ai: false,
  whisper: false,
  ffmpeg: false,
  guest_access_enabled: false,
})

const capabilities = ref(safeCapabilities())
const loaded = ref(false)
const error = ref('')

export function useCapabilities() {
  async function fetchCapabilities() {
    error.value = ''
    try {
      const res = await fetch(`${API_BASE}/capabilities`)
      if (!res.ok) {
        throw new Error(`capabilities ${res.status}`)
      }
      const data = await res.json()
      capabilities.value = {
        ai: data.ai === true,
        whisper: data.whisper === true,
        ffmpeg: data.ffmpeg === true,
        guest_access_enabled: data.guest_access_enabled === true,
      }
      return true
    } catch {
      capabilities.value = safeCapabilities()
      error.value = '无法获取服务能力，请稍后重试'
      return false
    } finally {
      loaded.value = true
    }
  }

  return {
    capabilities: readonly(capabilities),
    loaded: readonly(loaded),
    error: readonly(error),
    fetchCapabilities,
  }
}
