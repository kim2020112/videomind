import { reactive, ref } from 'vue'
import { useAuth } from './useAuth.js'

export function usePlatformConfig() {
  const { getAuthHeaders } = useAuth()
  const platforms = ref({})
  const pending = reactive({ load: false, bilibili: '', douyin: '' })
  const feedback = reactive({})
  const loadError = ref('')

  async function request(path, method = 'GET', body) {
    const response = await fetch(`/api/admin/platform-config${path}`, {
      method, credentials: 'same-origin',
      headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || '请求失败，请重试')
    return data
  }

  async function load() {
    pending.load = true
    loadError.value = ''
    try {
      const data = await request('')
      platforms.value = data.platforms || {}
    } catch (error) {
      loadError.value = error.message
    } finally {
      pending.load = false
    }
  }

  async function operate(platform, cookie, action) {
    if (pending[platform]) return null
    pending[platform] = action
    delete feedback[platform]
    try {
      const result = await request(`/${platform}${action === 'validate' ? '/validate' : ''}`, action === 'validate' ? 'POST' : 'PUT', { cookie })
      feedback[platform] = action === 'save'
        ? { type: 'success', message: cookie.trim() ? (result.platforms?.[platform]?.used_for_requests === false ? 'Cookie 已保存；当前自动任务保持匿名，仍可手动验证登录态' : 'Cookie 已保存，后续任务立即使用新配置') : '已保留当前 Cookie' }
        : { type: result.status === 'unknown' ? 'warning' : result.valid ? 'success' : 'error', message: result.message }
      if (action === 'save') platforms.value = result.platforms || {}
      else await load()
      return result
    } catch (error) {
      feedback[platform] = { type: 'error', message: error.message }
      return null
    } finally {
      pending[platform] = ''
    }
  }

  return { platforms, pending, feedback, loadError, load,
    save: (platform, cookie) => operate(platform, cookie, 'save'),
    validate: (platform, cookie) => operate(platform, cookie, 'validate') }
}
