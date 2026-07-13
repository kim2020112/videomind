import { ref } from 'vue'
import { useAuth } from './useAuth.js'

const API_BASE = '/api/admin'

// 全局单例状态
const providers = ref([])
const active = ref({ provider_id: '', model_id: '' })
const loading = ref(false)
const saving = ref(false)
const testResult = ref(null)

export function useAdminConfig() {
  const { getAuthHeaders } = useAuth()

  function withAuth(options = {}) {
    return {
      ...options,
      credentials: 'same-origin',
      headers: {
        ...getAuthHeaders(),
        ...(options.headers || {}),
      },
    }
  }

  async function fetchProviders() {
    loading.value = true
    try {
      const res = await fetch(`${API_BASE}/ai-config`, withAuth())
      if (!res.ok) throw new Error('获取配置失败')
      const data = await res.json()
      providers.value = data.providers || []
      active.value = data.active || { provider_id: '', model_id: '' }
    } catch (e) {
      console.error('获取 AI 配置失败:', e)
    } finally {
      loading.value = false
    }
  }

  // ── 服务商 CRUD ──

  async function addProvider(data) {
    saving.value = true
    try {
      const res = await fetch(`${API_BASE}/ai-config/providers`, withAuth({
        method: 'POST',
        body: JSON.stringify(data),
      }))
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '添加失败')
      }
      await fetchProviders()
      return true
    } finally {
      saving.value = false
    }
  }

  async function updateProvider(pid, data) {
    saving.value = true
    try {
      const res = await fetch(`${API_BASE}/ai-config/providers/${pid}`, withAuth({
        method: 'PUT',
        body: JSON.stringify(data),
      }))
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '更新失败')
      }
      await fetchProviders()
      return true
    } finally {
      saving.value = false
    }
  }

  async function deleteProvider(pid) {
    saving.value = true
    try {
      const res = await fetch(`${API_BASE}/ai-config/providers/${pid}`, withAuth({
        method: 'DELETE',
      }))
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '删除失败')
      }
      await fetchProviders()
      return true
    } finally {
      saving.value = false
    }
  }

  async function testProvider(pid) {
    testResult.value = null
    loading.value = true
    try {
      const res = await fetch(`${API_BASE}/ai-config/providers/${pid}/test`, withAuth({
        method: 'POST',
      }))
      testResult.value = await res.json()
    } catch (e) {
      testResult.value = { success: false, message: e.message, model: '' }
    } finally {
      loading.value = false
    }
  }

  // ── 模型 CRUD ──

  async function addModel(pid, data) {
    saving.value = true
    try {
      const res = await fetch(`${API_BASE}/ai-config/providers/${pid}/models`, withAuth({
        method: 'POST',
        body: JSON.stringify(data),
      }))
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '添加失败')
      }
      await fetchProviders()
      return true
    } finally {
      saving.value = false
    }
  }

  async function updateModel(pid, mid, data) {
    saving.value = true
    try {
      const res = await fetch(`${API_BASE}/ai-config/providers/${pid}/models/${mid}`, withAuth({
        method: 'PUT',
        body: JSON.stringify(data),
      }))
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '更新失败')
      }
      await fetchProviders()
      return true
    } finally {
      saving.value = false
    }
  }

  async function deleteModel(pid, mid) {
    saving.value = true
    try {
      const res = await fetch(`${API_BASE}/ai-config/providers/${pid}/models/${mid}`, withAuth({
        method: 'DELETE',
      }))
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '删除失败')
      }
      await fetchProviders()
      return true
    } finally {
      saving.value = false
    }
  }

  async function switchModel(pid, mid) {
    try {
      const res = await fetch(`${API_BASE}/ai-config/switch`, withAuth({
        method: 'POST',
        body: JSON.stringify({ provider_id: pid, model_id: mid }),
      }))
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '切换失败')
      }
      active.value = { provider_id: pid, model_id: mid }
      return true
    } catch (e) {
      throw e
    }
  }

  async function testConnection(data) {
    testResult.value = null
    loading.value = true
    try {
      const res = await fetch(`${API_BASE}/ai-config/test`, withAuth({
        method: 'POST',
        body: JSON.stringify(data),
      }))
      testResult.value = await res.json()
    } catch (e) {
      testResult.value = { success: false, message: e.message, model: '' }
    } finally {
      loading.value = false
    }
  }

  return {
    providers,
    active,
    loading,
    saving,
    testResult,
    fetchProviders,
    addProvider,
    updateProvider,
    deleteProvider,
    testProvider,
    addModel,
    updateModel,
    deleteModel,
    switchModel,
    testConnection,
  }
}
