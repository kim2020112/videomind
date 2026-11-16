import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./useAuth.js', () => ({
  useAuth: () => ({
    getAuthHeaders: () => ({ Authorization: 'Bearer test-session' }),
  }),
}))

describe('useBloggers', () => {
  afterEach(() => vi.useRealTimers())
  beforeEach(() => {
    vi.resetModules()
    vi.unstubAllGlobals()
  })

  async function loadComposable() {
    const { useBloggers } = await import('./useBloggers.js')
    return useBloggers()
  }

  function okJson(data) {
    return { ok: true, json: () => Promise.resolve(data) }
  }

  it('lists bloggers with auth headers', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson({ bloggers: [{ id: 1 }] }))
    vi.stubGlobal('fetch', fetchMock)
    const api = await loadComposable()

    const result = await api.listBloggers()

    expect(result).toEqual([{ id: 1 }])
    expect(api.bloggers.value).toEqual([{ id: 1 }])
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/bloggers')
    expect(options.headers.Authorization).toBe('Bearer test-session')
  })

  it('posts add blogger payload and surfaces API errors', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(okJson({ sub: { id: 2 }, sync: { id: 3 } }))
      .mockResolvedValueOnce({ ok: false, json: () => Promise.resolve({ detail: '这不是 UP 主空间链接' }) })
    vi.stubGlobal('fetch', fetchMock)
    const api = await loadComposable()

    await api.addBlogger('475210')
    expect(fetchMock.mock.calls[0][1].method).toBe('POST')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ input: '475210' })

    await expect(api.addBlogger('bad')).rejects.toThrow('这不是 UP 主空间链接')
    expect(api.error.value).toBe('这不是 UP 主空间链接')
  })

  it('creates batch and fetches detail', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(okJson({ id: 'b1', usage: { allowed: true } }))
      .mockResolvedValueOnce(okJson({ id: 'b1', items: [] }))
    vi.stubGlobal('fetch', fetchMock)
    const api = await loadComposable()

    const batch = await api.createBatch(2, { selection: { video_ids: [1] }, mode: 'full' })
    expect(batch.id).toBe('b1')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/bloggers/2/batches')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).mode).toBe('full')

    const detail = await api.getBatch('b1')
    expect(detail.items).toEqual([])
    expect(fetchMock.mock.calls[1][0]).toBe('/api/batches/b1')
  })

  it('sends batch actions and reports failures', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(okJson({ id: 'b1', status: 'cancelled' }))
      .mockResolvedValueOnce({ ok: false, json: () => Promise.resolve({ detail: '批次不存在' }) })
    vi.stubGlobal('fetch', fetchMock)
    const api = await loadComposable()

    const updated = await api.batchAction('b1', 'cancel')
    expect(updated.status).toBe('cancelled')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ action: 'cancel' })

    await expect(api.batchAction('b1', 'resume')).rejects.toThrow('批次不存在')
  })

  it('lists videos and pages', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(okJson({ total: 1, items: [{ id: 5 }] }))
      .mockResolvedValueOnce(okJson({ pages: [{ cid: 11, page: 1 }] }))
    vi.stubGlobal('fetch', fetchMock)
    const api = await loadComposable()

    await api.listVideos(2, { q: '关键词', limit: 30 })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/bloggers/2/videos?q=%E5%85%B3%E9%94%AE%E8%AF%8D&limit=30')

    await api.listPages(2, 5)
    expect(fetchMock.mock.calls[1][0]).toBe('/api/bloggers/2/videos/5/pages')
    expect(api.pages.value).toEqual([{ cid: 11, page: 1 }])
  })

  it('previews, syncs and cancels with proper request shapes', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(okJson({ profile: { uid: '1' }, already_subscribed: false }))
      .mockResolvedValueOnce(okJson({ sync: { id: 9 }, already_running: false }))
      .mockResolvedValueOnce(okJson({ cancelled: true, sync: { id: 9 } }))
      .mockResolvedValueOnce(okJson({ sync: { id: 9, mode: 'deep', page: 2 } }))
      .mockResolvedValueOnce(okJson({ will_remove: { videos: 3 }, preserved: {} }))
    vi.stubGlobal('fetch', fetchMock)
    const api = await loadComposable()

    await api.previewBlogger('475210')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/bloggers/preview')

    await api.syncBlogger(2, { mode: 'deep' })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/bloggers/2/sync')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ mode: 'deep' })

    await api.cancelSync(2)
    expect(fetchMock.mock.calls[2][0]).toBe('/api/bloggers/2/sync/cancel')

    const status = await api.getSyncStatus(2)
    expect(status.sync.mode).toBe('deep')
    expect(fetchMock.mock.calls[3][0]).toBe('/api/bloggers/2/sync')

    const preview = await api.getDeletionPreview(2)
    expect(preview.will_remove.videos).toBe(3)
    expect(fetchMock.mock.calls[4][0]).toBe('/api/bloggers/2/deletion-preview')
  })

  it('replaces video pages and tracks hasMore and learned filter', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(okJson({ total: 3, learned_total: 1, items: [{ id: 1 }, { id: 2 }] }))
      .mockResolvedValueOnce(okJson({ total: 3, offset: 2, learned_total: 1, items: [{ id: 3 }] }))
    vi.stubGlobal('fetch', fetchMock)
    const api = await loadComposable()

    await api.listVideos(2, { limit: 2 })
    expect(api.videosHasMore.value).toBe(true)
    expect(api.videos.value).toHaveLength(2)

    await api.listVideos(2, { limit: 2, offset: 2 })
    expect(api.videos.value).toHaveLength(1)
    expect(api.videosHasMore.value).toBe(false)
    expect(api.videosLearnedTotal.value).toBe(1)
    expect(fetchMock.mock.calls[1][0]).toContain('offset=2')
  })
  it('ignores a slower earlier page response', async () => {
    let finishOld
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
      .mockResolvedValueOnce(okJson({ total: 40, offset: 20, items: [{ id: 21 }] }))
    vi.stubGlobal('fetch', fetchMock)
    const api = await loadComposable()
    const old = api.listVideos(2, { offset: 0 })
    await api.listVideos(2, { offset: 20 })
    finishOld(okJson({ total: 40, items: [{ id: 1 }] }))
    expect(await old).toBeNull()
    expect(api.videos.value).toEqual([{ id: 21 }])
  })

  it('does not overlap batch requests and discards a stopped batch response', async () => {
    vi.useFakeTimers()
    let finish
    const fetchMock = vi.fn(() => new Promise(resolve => { finish = resolve }))
    vi.stubGlobal('fetch', fetchMock)
    const api = await loadComposable()
    const changed = vi.fn()
    api.startBatchPolling('old', changed)
    await vi.advanceTimersByTimeAsync(12000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    api.stopBatchPolling()
    finish(okJson({ id: 'old', status: 'done' }))
    await vi.advanceTimersByTimeAsync(30000)
    expect(changed).not.toHaveBeenCalled()
    expect(api.currentBatch.value).toBeNull()
    expect(api.batchLoading.value).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('keeps tracking a paused batch so a resumed task remains observable', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(okJson({ id: 'b1', status: 'paused' }))
      .mockResolvedValueOnce(okJson({ id: 'b1', status: 'running' }))
      .mockResolvedValueOnce(okJson({ id: 'b1', status: 'done' }))
    vi.stubGlobal('fetch', fetchMock)
    const api = await loadComposable()
    api.startBatchPolling('b1')
    await vi.advanceTimersByTimeAsync(15000)
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(api.currentBatch.value.status).toBe('done')
    api.stopBatchPolling()
  })

})
