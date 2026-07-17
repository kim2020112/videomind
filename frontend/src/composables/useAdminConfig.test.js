import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./useAuth.js', () => ({
  useAuth: () => ({
    getAuthHeaders: () => ({ Authorization: 'Bearer admin-window-session' }),
  }),
}))

function response(data, ok = true) {
  return { ok, json: vi.fn().mockResolvedValue(data) }
}

function configuredConnection() {
  return {
    id: 'c1',
    name: 'Gateway',
    primary_model_id: 'm1',
    models: [{
      id: 'm1',
      name: 'Model',
      model: 'model-1',
      discovery_status: 'available',
      test_status: 'untested',
      test_message: '',
      tested_at: '',
    }],
  }
}

describe('useAdminConfig', () => {
  beforeEach(() => {
    vi.resetModules()
    global.fetch = vi.fn().mockResolvedValue(response({ connections: [], active: {} }))
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('sends the current window session when loading admin data', async () => {
    const { useAdminConfig } = await import('./useAdminConfig.js')
    await useAdminConfig().fetchProviders()

    expect(global.fetch).toHaveBeenCalledWith('/api/admin/ai-config', expect.objectContaining({
      headers: expect.objectContaining({ Authorization: 'Bearer admin-window-session' }),
    }))
  })

  it('expires success at 3 seconds and errors at 8 seconds', async () => {
    vi.useFakeTimers()
    const connection = configuredConnection()
    global.fetch
      .mockResolvedValueOnce(response({ connection, active: { connection_id: 'c1', model_id: 'm1' } }))
      .mockResolvedValueOnce(response({ detail: '保存失败' }, false))
    const { useAdminConfig } = await import('./useAdminConfig.js')
    const api = useAdminConfig()

    await api.saveConnection({ name: 'Gateway' })
    expect(api.notification.value?.type).toBe('success')
    vi.advanceTimersByTime(2999)
    expect(api.notification.value).not.toBeNull()
    vi.advanceTimersByTime(1)
    expect(api.notification.value).toBeNull()

    await expect(api.saveConnection({ name: 'Gateway' })).rejects.toThrow('保存失败')
    expect(api.notification.value?.type).toBe('error')
    vi.advanceTimersByTime(7999)
    expect(api.notification.value).not.toBeNull()
    vi.advanceTimersByTime(1)
    expect(api.notification.value).toBeNull()
  })

  it('pauses notification expiry while hovered or focused and clears it immediately', async () => {
    vi.useFakeTimers()
    const connection = configuredConnection()
    global.fetch.mockResolvedValue(response({ connection, active: { connection_id: 'c1', model_id: 'm1' } }))
    const { useAdminConfig } = await import('./useAdminConfig.js')
    const api = useAdminConfig()

    await api.saveConnection({ name: 'Gateway' })
    vi.advanceTimersByTime(1000)
    api.pauseNotification()
    vi.advanceTimersByTime(10000)
    expect(api.notification.value?.paused).toBe(true)
    api.resumeNotification()
    vi.advanceTimersByTime(1999)
    expect(api.notification.value).not.toBeNull()
    vi.advanceTimersByTime(1)
    expect(api.notification.value).toBeNull()

    await api.saveConnection({ name: 'Gateway' })
    expect(api.notification.value).not.toBeNull()
    api.clearNotification()
    expect(api.notification.value).toBeNull()
  })

  it('clears stale data and exposes retryable load errors', async () => {
    global.fetch.mockResolvedValueOnce(response({ detail: '网络不可用' }, false))
    const { useAdminConfig } = await import('./useAdminConfig.js')
    const api = useAdminConfig()
    api.connections.value = [configuredConnection()]
    Object.assign(api.active, { connection_id: 'c1', model_id: 'm1' })

    await api.fetchConnections()

    expect(api.connections.value).toEqual([])
    expect(api.active).toMatchObject({ connection_id: '', model_id: '' })
    expect(api.loadError.value).toBe('网络不可用')
  })

  it('blocks duplicate deletes and applies the server fallback active state', async () => {
    let resolveDelete
    global.fetch.mockReturnValueOnce(new Promise(resolve => { resolveDelete = resolve }))
    const { useAdminConfig } = await import('./useAdminConfig.js')
    const api = useAdminConfig()

    const first = api.deleteConnection('c1')
    const duplicate = api.deleteConnection('c1')
    expect(global.fetch).toHaveBeenCalledTimes(1)
    resolveDelete(response({ connections: [configuredConnection()], active: { connection_id: 'c1', model_id: 'm1' } }))
    await first

    expect(await duplicate).toBeNull()
    expect(api.active).toMatchObject({ connection_id: 'c1', model_id: 'm1' })
  })

  it('does not mutate active on a failed switch and reports the error beside the connection', async () => {
    global.fetch.mockResolvedValueOnce(response({ detail: '模型不可用' }, false))
    const { useAdminConfig } = await import('./useAdminConfig.js')
    const api = useAdminConfig()
    Object.assign(api.active, { connection_id: 'c1', model_id: 'm1' })

    const result = await api.switchModel('c1', 'm2')

    expect(result).toBeNull()
    expect(api.active).toMatchObject({ connection_id: 'c1', model_id: 'm1' })
    expect(api.connectionFeedback.c1).toMatchObject({ action: 'switch', type: 'error', message: '模型不可用' })
  })

  it('persists a failed model test in local model state independently of discovery', async () => {
    global.fetch.mockResolvedValueOnce(response({
      success: false,
      message: 'WAF blocked',
      test_status: 'failed',
      tested_at: '2026-07-17T00:00:00Z',
    }))
    const { useAdminConfig } = await import('./useAdminConfig.js')
    const api = useAdminConfig()
    api.connections.value = [configuredConnection()]

    await api.testModel('c1', 'm1')
    const stored = api.connections.value[0].models[0]

    expect(stored.discovery_status).toBe('available')
    expect(stored.test_status).toBe('failed')
    expect(api.modelFeedback['c1:m1']).toMatchObject({ type: 'error', message: 'WAF blocked' })
  })

  it('clears model feedback and cancels its expiry timer', async () => {
    vi.useFakeTimers()
    global.fetch.mockResolvedValueOnce(response({
      success: false,
      message: 'API 响应中未找到文本内容',
      test_status: 'failed',
      tested_at: '2026-07-17T00:00:00Z',
    }))
    const { useAdminConfig } = await import('./useAdminConfig.js')
    const api = useAdminConfig()
    api.connections.value = [configuredConnection()]

    await api.testModel('c1', 'm1')
    expect(api.modelFeedback['c1:m1']).toBeDefined()
    expect(vi.getTimerCount()).toBe(1)

    api.clearModelFeedback('c1:m1')
    expect(api.modelFeedback['c1:m1']).toBeUndefined()
    expect(vi.getTimerCount()).toBe(0)

    api.modelFeedback['c1:m1'] = { type: 'error', message: 'new feedback' }
    vi.advanceTimersByTime(8000)
    expect(api.modelFeedback['c1:m1']).toMatchObject({ message: 'new feedback' })
  })
})
