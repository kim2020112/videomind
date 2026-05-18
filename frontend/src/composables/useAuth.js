import { ref, computed } from 'vue'

const API_BASE = '/api'

// 全局单例状态
const user = ref(null)
const usage = ref({ used: 0, limit: 0, allowed: true })
const guestId = ref('')
const guestSig = ref('')
const loading = ref(false)
const initialized = ref(false)

export function useAuth() {
  // 生成兼容 HTTP/HTTPS 的 UUID
  function _generateId() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
      return crypto.randomUUID()
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = Math.random() * 16 | 0
      return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16)
    })
  }

  // 初始化：生成游客 ID + 拉取 /me
  async function init() {
    if (initialized.value) return
    initialized.value = true
    await ensureGuestId()
    await fetchMe()
    // 如果没拿到用户信息，延迟重试一次（处理 session cookie 时序问题）
    if (!user.value) {
      await new Promise(r => setTimeout(r, 300))
      await fetchMe()
    }
  }

  // 确保游客 device_id 和签名存在
  async function ensureGuestId() {
    let id = localStorage.getItem('vm_guest_id')
    let sig = localStorage.getItem('vm_guest_sig')
    if (id && sig) {
      guestId.value = id
      guestSig.value = sig
      return
    }
    // 生成新的 device_id 并请求签名
    id = _generateId()
    try {
      const resp = await fetch(`${API_BASE}/auth/guest-sign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_id: id }),
      })
      const data = await resp.json()
      sig = data.signature
      localStorage.setItem('vm_guest_id', id)
      localStorage.setItem('vm_guest_sig', sig)
      guestId.value = id
      guestSig.value = sig
    } catch {
      // 签名失败，仍保存 id
      guestId.value = id
    }
  }

  // 拉取当前用户信息
  async function fetchMe() {
    try {
      const headers = {}
      // 游客也带上身份 header，否则服务端无法识别 → usage 返回 0
      if (!user.value && guestId.value) {
        headers['X-Guest-Id'] = guestId.value
        if (guestSig.value) headers['X-Guest-Sig'] = guestSig.value
      }
      const res = await fetch(`${API_BASE}/auth/me`, {
        credentials: 'same-origin',
        headers,
      })
      if (!res.ok) {
        // 服务端明确拒绝（401/403），清除本地状态
        user.value = null
        localStorage.removeItem('vm_user')
        return
      }
      const data = await res.json()
      if (data.logged_in) {
        user.value = data.user
        localStorage.setItem('vm_user', JSON.stringify(data.user))
      } else {
        user.value = null
        localStorage.removeItem('vm_user')
      }
      usage.value = data.usage || { used: 0, limit: 0, allowed: true }
    } catch {
      _restoreFromStorage()
    }
  }

  // 从 localStorage 恢复用户信息（降级方案）
  function _restoreFromStorage() {
    try {
      const stored = localStorage.getItem('vm_user')
      if (stored) {
        user.value = JSON.parse(stored)
      }
    } catch { /* ignore */ }
  }

  // 注册
  async function register(username, password) {
    loading.value = true
    try {
      const res = await fetch(`${API_BASE}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ username, password }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '注册失败')
      }
      await fetchMe()
      return true
    } finally {
      loading.value = false
    }
  }

  // 登录
  async function login(username, password) {
    loading.value = true
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ username, password }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '登录失败')
      }
      await fetchMe()
      return true
    } finally {
      loading.value = false
    }
  }

  // 退出
  async function logout() {
    await fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      credentials: 'same-origin',
    })
    user.value = null
    localStorage.removeItem('vm_user')
    usage.value = { used: 0, limit: 0, allowed: true }
  }

  const isLoggedIn = computed(() => !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const displayName = computed(() => {
    if (user.value) return user.value.username
    return '游客'
  })

  // 刷新使用次数（AI 调用后调用，轻量接口不返回用户信息）
  async function refreshUsage() {
    try {
      const headers = {}
      if (!user.value && guestId.value) {
        headers['X-Guest-Id'] = guestId.value
        if (guestSig.value) headers['X-Guest-Sig'] = guestSig.value
      }
      const res = await fetch(`${API_BASE}/auth/usage`, {
        credentials: 'same-origin',
        headers,
      })
      if (res.ok) {
        usage.value = await res.json()
      }
    } catch { /* ignore */ }
  }

  // 构建请求 headers（供其他 composable 使用）
  function getAuthHeaders() {
    const headers = { 'Content-Type': 'application/json' }
    if (!user.value && guestId.value) {
      headers['X-Guest-Id'] = guestId.value
      if (guestSig.value) {
        headers['X-Guest-Sig'] = guestSig.value
      }
    }
    return headers
  }

  return {
    user,
    usage,
    guestId,
    guestSig,
    loading,
    isLoggedIn,
    isAdmin,
    displayName,
    init,
    fetchMe,
    refreshUsage,
    register,
    login,
    logout,
    getAuthHeaders,
  }
}
