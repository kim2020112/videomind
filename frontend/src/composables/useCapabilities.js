import { ref, readonly } from 'vue'

const API_BASE = '/api'

// 全局单例状态
const capabilities = ref({ ai: true, whisper: true, ffmpeg: true })
const loaded = ref(false)

export function useCapabilities() {
  async function fetchCapabilities() {
    try {
      const res = await fetch(`${API_BASE}/capabilities`)
      if (res.ok) {
        capabilities.value = await res.json()
      }
    } catch {
      // 网络失败时保持默认值（全部可用）
    }
    loaded.value = true
  }

  return {
    capabilities: readonly(capabilities),
    loaded: readonly(loaded),
    fetchCapabilities,
  }
}
