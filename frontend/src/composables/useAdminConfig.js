import { getCurrentScope, onScopeDispose, reactive, ref, shallowRef } from 'vue'
import { useAuth } from './useAuth.js'

const SUCCESS_NOTICE_MS = 3000
const ERROR_NOTICE_MS = 8000
const TEST_SUCCESS_MS = 4000

export function useAdminConfig() {
  const { getAuthHeaders } = useAuth()
  const connections = ref([])
  const active = reactive({ connection_id: '', model_id: '' })
  const pending = reactive({
    load: false,
    save: false,
    delete: '',
    discover: false,
    refresh: {},
    switch: '',
    test: {},
  })
  const loadError = shallowRef('')
  const notification = shallowRef(null)
  const connectionFeedback = reactive({})
  const modelFeedback = reactive({})

  let notificationTimer = null
  let notificationStartedAt = 0
  const feedbackTimers = new Map()

  const options = (method = 'GET', body) => ({
    method,
    credentials: 'same-origin',
    headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })

  async function request(path, method = 'GET', body) {
    const response = await fetch(`/api/admin/ai-config${path}`, options(method, body))
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || '请求失败，请重试')
    return data
  }

  function assignConfig(data) {
    connections.value = data.connections || []
    Object.assign(active, data.active || { connection_id: '', model_id: '' })
  }

  function replaceConnection(connection) {
    const index = connections.value.findIndex(item => item.id === connection.id)
    connections.value = index < 0
      ? [...connections.value, connection]
      : connections.value.map(item => item.id === connection.id ? connection : item)
  }

  function clearNotification() {
    if (notificationTimer) window.clearTimeout(notificationTimer)
    notificationTimer = null
    notification.value = null
  }

  function scheduleNotification() {
    if (!notification.value || notification.value.paused) return
    notificationStartedAt = Date.now()
    notificationTimer = window.setTimeout(clearNotification, notification.value.remaining)
  }

  function showNotification(type, message) {
    clearNotification()
    const duration = type === 'success' ? SUCCESS_NOTICE_MS : ERROR_NOTICE_MS
    notification.value = { type, message, duration, remaining: duration, paused: false }
    scheduleNotification()
  }

  function pauseNotification() {
    if (!notification.value || notification.value.paused) return
    if (notificationTimer) window.clearTimeout(notificationTimer)
    notificationTimer = null
    const elapsed = Date.now() - notificationStartedAt
    notification.value = {
      ...notification.value,
      remaining: Math.max(0, notification.value.remaining - elapsed),
      paused: true,
    }
  }

  function resumeNotification() {
    if (!notification.value?.paused) return
    notification.value = { ...notification.value, paused: false }
    if (notification.value.remaining <= 0) clearNotification()
    else scheduleNotification()
  }

  function clearFeedbackTimer(key) {
    const timer = feedbackTimers.get(key)
    if (timer) window.clearTimeout(timer)
    feedbackTimers.delete(key)
  }

  function showFeedback(collection, key, value, duration) {
    clearFeedbackTimer(key)
    collection[key] = value
    feedbackTimers.set(key, window.setTimeout(() => {
      delete collection[key]
      feedbackTimers.delete(key)
    }, duration))
  }

  function clearFeedback() {
    clearNotification()
    feedbackTimers.forEach(timer => window.clearTimeout(timer))
    feedbackTimers.clear()
    Object.keys(connectionFeedback).forEach(key => delete connectionFeedback[key])
    Object.keys(modelFeedback).forEach(key => delete modelFeedback[key])
  }

  function clearModelFeedback(key) {
    if (!key) return
    clearFeedbackTimer(key)
    delete modelFeedback[key]
  }

  async function fetchConnections() {
    if (pending.load) return null
    pending.load = true
    loadError.value = ''
    connections.value = []
    Object.assign(active, { connection_id: '', model_id: '' })
    try {
      const data = await request('')
      assignConfig(data)
      return data
    } catch (error) {
      loadError.value = error.message
      return null
    } finally {
      pending.load = false
    }
  }

  async function discoverModels(credentials) {
    if (pending.discover) return null
    pending.discover = true
    try {
      return await request('/discover', 'POST', credentials)
    } finally {
      pending.discover = false
    }
  }

  async function saveConnection(payload, id = '') {
    if (pending.save) return null
    pending.save = true
    try {
      const data = await request(id ? `/connections/${id}` : '/connections', id ? 'PUT' : 'POST', payload)
      replaceConnection(data.connection)
      Object.assign(active, data.active)
      showNotification('success', '连接已保存')
      return data.connection
    } catch (error) {
      showNotification('error', error.message)
      throw error
    } finally {
      pending.save = false
    }
  }

  async function deleteConnection(id) {
    if (pending.delete) return null
    pending.delete = id
    try {
      const data = await request(`/connections/${id}`, 'DELETE')
      assignConfig(data)
      showNotification('success', '连接已删除')
      return data
    } finally {
      pending.delete = ''
    }
  }

  async function refreshConnection(id) {
    if (pending.refresh[id]) return null
    pending.refresh[id] = true
    delete connectionFeedback[id]
    try {
      const connection = await request(`/connections/${id}/refresh`, 'POST')
      replaceConnection(connection)
      showFeedback(connectionFeedback, id, { action: 'refresh', type: 'success', message: '模型目录已更新' }, TEST_SUCCESS_MS)
      return connection
    } catch (error) {
      showFeedback(connectionFeedback, id, { action: 'refresh', type: 'error', message: error.message }, ERROR_NOTICE_MS)
      return null
    } finally {
      delete pending.refresh[id]
    }
  }

  async function testModel(connectionId, modelId) {
    const key = `${connectionId}:${modelId}`
    if (pending.test[key]) return null
    pending.test[key] = true
    delete modelFeedback[key]
    try {
      const result = await request(`/connections/${connectionId}/models/${modelId}/test`, 'POST')
      const connection = connections.value.find(item => item.id === connectionId)
      const model = connection?.models.find(item => item.id === modelId)
      if (model) {
        model.test_status = result.test_status
        model.test_message = result.message
        model.tested_at = result.tested_at
      }
      const success = result.success === true
      showFeedback(modelFeedback, key, {
        type: success ? 'success' : 'error',
        message: success
          ? (result.message || '模型响应正常').replace(/^模型可用[：:]?\s*/u, '')
          : result.message || '模型未通过可用性测试',
      }, success ? TEST_SUCCESS_MS : ERROR_NOTICE_MS)
      return result
    } catch (error) {
      showFeedback(modelFeedback, key, { type: 'error', message: error.message }, ERROR_NOTICE_MS)
      return null
    } finally {
      delete pending.test[key]
    }
  }

  async function switchModel(connectionId, modelId) {
    if (pending.switch) return null
    pending.switch = connectionId
    delete connectionFeedback[connectionId]
    try {
      const data = await request('/switch', 'POST', { connection_id: connectionId, model_id: modelId })
      replaceConnection(data.connection)
      Object.assign(active, data.active)
      showFeedback(connectionFeedback, connectionId, { action: 'switch', type: 'success', message: '主力模型已切换' }, TEST_SUCCESS_MS)
      return data
    } catch (error) {
      showFeedback(connectionFeedback, connectionId, { action: 'switch', type: 'error', message: error.message }, ERROR_NOTICE_MS)
      return null
    } finally {
      pending.switch = ''
    }
  }

  if (getCurrentScope()) onScopeDispose(clearFeedback)

  return {
    connections,
    active,
    pending,
    loadError,
    notification,
    connectionFeedback,
    modelFeedback,
    fetchConnections,
    fetchProviders: fetchConnections,
    discoverModels,
    saveConnection,
    deleteConnection,
    refreshConnection,
    testModel,
    switchModel,
    clearNotification,
    pauseNotification,
    resumeNotification,
    clearModelFeedback,
    clearFeedback,
  }
}

export { ERROR_NOTICE_MS, SUCCESS_NOTICE_MS, TEST_SUCCESS_MS }
