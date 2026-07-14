import { ref, computed } from 'vue'

const API_BASE = '/api'

// 全局单例状态
const user = ref(null)
const usage = ref({ used: 0, limit: 0, allowed: true })
const guestId = ref('')
const guestSig = ref('')
const loading = ref(false)
const initialized = ref(false)
const sessionId = ref(_readSessionValue('vm_session_id'))
const sessionMode = ref(_readSessionValue('vm_session_mode'))

function _readSessionValue(key) {
  try {
    return sessionStorage.getItem(key) || ''
  } catch {
    return ''
  }
}

function _setSessionValue(key, value) {
  try {
    if (value) sessionStorage.setItem(key, value)
    else sessionStorage.removeItem(key)
  } catch { /* ignore */ }
}

function _clearWindowUser() {
  user.value = null
  sessionId.value = ''
  sessionMode.value = 'guest'
  _setSessionValue('vm_session_id', '')
  _setSessionValue('vm_session_mode', 'guest')
  _setSessionValue('vm_user', '')
}

function _setWindowSession(value) {
  sessionId.value = value
  sessionMode.value = ''
  _setSessionValue('vm_session_id', value)
  _setSessionValue('vm_session_mode', '')
}

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
  }

  // 确保游客 device_id 和签名存在
  async function ensureGuestId() {
    let id = localStorage.getItem('vm_guest_id')
    let sig = localStorage.getItem('vm_guest_sig')
    if (sig === 'undefined' || sig === 'null') {
      localStorage.removeItem('vm_guest_sig')
      sig = ''
    }
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
      if (!resp.ok) {
        throw new Error('guest-sign failed')
      }
      const data = await resp.json()
      sig = data.signature
      if (!sig) {
        throw new Error('guest-sign missing signature')
      }
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
      const headers = getAuthHeaders()
      const res = await fetch(`${API_BASE}/auth/me`, {
        headers,
      })
      if (!res.ok) {
        // 服务端明确拒绝（401/403），清除本地状态
        _clearWindowUser()
        return
      }
      const data = await res.json()
      if (data.logged_in) {
        user.value = data.user
        _setSessionValue('vm_user', JSON.stringify(data.user))
      } else {
        _clearWindowUser()
      }
      usage.value = data.usage || { used: 0, limit: 0, allowed: true }
    } catch {
      _restoreFromStorage()
    }
  }

  // 从当前窗口恢复用户信息（网络异常时的降级方案）
  function _restoreFromStorage() {
    try {
      const stored = sessionStorage.getItem('vm_user')
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
        body: JSON.stringify({ username, password }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '注册失败')
      }
      const data = await res.json().catch(() => ({}))
      if (typeof data.session_id !== 'string' || !data.session_id.trim()) {
        throw new Error('注册响应缺少 Session')
      }
      _setWindowSession(data.session_id.trim())
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
        body: JSON.stringify({ username, password }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '登录失败')
      }
      const data = await res.json().catch(() => ({}))
      if (typeof data.session_id !== 'string' || !data.session_id.trim()) {
        throw new Error('登录响应缺少 Session')
      }
      _setWindowSession(data.session_id.trim())
      await fetchMe()
      return true
    } finally {
      loading.value = false
    }
  }

  // 退出
  async function logout() {
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
    } finally {
      _clearWindowUser()
      usage.value = { used: 0, limit: 0, allowed: true }
    }
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
      const headers = getAuthHeaders()
      const res = await fetch(`${API_BASE}/auth/usage`, {
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
    if (sessionId.value) {
      headers.Authorization = `Bearer ${sessionId.value}`
    } else if (!user.value && guestId.value) {
      if (sessionMode.value === 'guest') {
        headers['X-Session-Mode'] = 'guest'
      }
      headers['X-Guest-Id'] = guestId.value
      if (guestSig.value) {
        headers['X-Guest-Sig'] = guestSig.value
      }
    }
    return headers
  }

  // WebSocket、video src 等不能设置普通请求头，改用同一窗口凭据的查询参数。
  function getAuthQueryParams() {
    const params = new URLSearchParams()
    if (sessionId.value) {
      params.set('session_id', sessionId.value)
    } else if (!user.value && guestId.value) {
      if (sessionMode.value === 'guest') params.set('session_mode', 'guest')
      params.set('guest_id', guestId.value)
      if (guestSig.value) params.set('guest_sig', guestSig.value)
    }
    return params
  }

  return {
    user,
    usage,
    guestId,
    guestSig,
    sessionId,
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
    getAuthQueryParams,
  }
}
