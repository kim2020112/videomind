import { getCurrentScope, onScopeDispose, reactive, ref, shallowRef } from 'vue'
import { useAuth } from './useAuth.js'
import { createSerialPoller } from '../utils/serialPoller.js'

const POLL_INTERVAL_MS = 3000

export function useBloggers() {
  const { getAuthHeaders } = useAuth()
  const bloggers = ref([])
  const bloggersLoading = ref(false)
  const bloggersError = shallowRef('')
  const videos = ref([])
  const videosTotal = ref(0)
  const videosLearnedTotal = ref(0)
  const videosSubtitleTotal = ref(0)
  const videosMatchedTotal = ref(0)
  const videosHasMore = ref(false)
  const videosLoading = ref(false)
  const pages = ref([])
  const pagesLoading = ref(false)
  const batches = ref([])
  const currentBatch = ref(null)
  const batchLoading = ref(false)
  const pending = reactive({
    add: false, preview: false, sync: '', remove: '',
    createBatch: false, action: '', update: '', cancelSync: '',
  })
  const error = shallowRef('')

  const batchPoller = createSerialPoller(POLL_INTERVAL_MS)
  const syncPoller = createSerialPoller(POLL_INTERVAL_MS)
  let batchEpoch = 0

  const options = (method = 'GET', body) => ({
    method,
    credentials: 'same-origin',
    headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })

  async function request(path, method = 'GET', body, base = '/api') {
    const response = await fetch(`${base}${path}`, options(method, body))
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || '请求失败，请重试')
    return data
  }

  function setError(err) {
    error.value = err?.message || String(err || '')
    return null
  }

  async function listBloggers() {
    bloggersLoading.value = true
    bloggersError.value = ''
    try {
      const data = await request('/bloggers')
      bloggers.value = data.bloggers || []
      return bloggers.value
    } catch (err) {
      bloggersError.value = err?.message || String(err || '')
      return setError(err)
    } finally {
      bloggersLoading.value = false
    }
  }

  async function previewBlogger(input) {
    pending.preview = true
    try {
      return await request('/bloggers/preview', 'POST', { input })
    } catch (err) {
      setError(err)
      throw err
    } finally {
      pending.preview = false
    }
  }

  async function addBlogger(input) {
    pending.add = true
    try {
      return await request('/bloggers', 'POST', { input })
    } catch (err) {
      setError(err)
      throw err
    } finally {
      pending.add = false
    }
  }

  async function updateBlogger(id, body) {
    pending.update = id
    try {
      return await request(`/bloggers/${id}`, 'PATCH', body)
    } catch (err) {
      setError(err)
      throw err
    } finally {
      pending.update = ''
    }
  }

  async function removeBlogger(id) {
    pending.remove = id
    try {
      return await request(`/bloggers/${id}`, 'DELETE')
    } catch (err) {
      setError(err)
      throw err
    } finally {
      pending.remove = ''
    }
  }

  async function getDeletionPreview(id) {
    try {
      return await request(`/bloggers/${id}/deletion-preview`)
    } catch (err) {
      setError(err)
      throw err
    }
  }

  async function syncBlogger(id, { mode = 'incremental' } = {}) {
    pending.sync = id
    try {
      return await request(`/bloggers/${id}/sync`, 'POST', { mode })
    } catch (err) {
      setError(err)
      throw err
    } finally {
      pending.sync = ''
    }
  }

  async function getSyncStatus(id) {
    try {
      return await request(`/bloggers/${id}/sync`)
    } catch (err) {
      return setError(err)
    }
  }

  async function cancelSync(id) {
    pending.cancelSync = id
    try {
      return await request(`/bloggers/${id}/sync/cancel`, 'POST')
    } catch (err) {
      setError(err)
      throw err
    } finally {
      pending.cancelSync = ''
    }
  }

  let videoEpoch = 0
  let pageEpoch = 0
  function invalidateVideoRequests() { videoEpoch += 1; pageEpoch += 1; pagesLoading.value = false }
  function applyVideoPage(data) {
    videos.value = data.items || []
    videosTotal.value = data.total || 0
    videosLearnedTotal.value = data.organized_total ?? data.learned_total ?? 0
    videosSubtitleTotal.value = data.subtitle_total || 0
    videosMatchedTotal.value = data.matched_total ?? data.total ?? 0
    videosHasMore.value = (data.offset || 0) + videos.value.length < videosTotal.value
  }
  async function listVideos(subId, params = {}, { quiet = false } = {}) {
    const ticket = ++videoEpoch
    videosLoading.value = !quiet
    try {
      const query = new URLSearchParams()
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
      })
      const data = await request(`/bloggers/${subId}/videos?${query}`)
      if (ticket !== videoEpoch) return null
      applyVideoPage(data)
      return data
    } catch (err) {
      if (ticket === videoEpoch) return setError(err)
      return null
    } finally {
      if (ticket === videoEpoch) videosLoading.value = false
    }
  }

  async function listPages(subId, videoId) {
    const ticket = ++pageEpoch
    pagesLoading.value = true
    pages.value = []
    try {
      const data = await request(`/bloggers/${subId}/videos/${videoId}/pages`)
      if (ticket !== pageEpoch) return null
      pages.value = data.pages || []
      return pages.value
    } catch (err) {
      return setError(err)
    } finally {
      if (ticket === pageEpoch) pagesLoading.value = false
    }
  }

  async function createBatch(subId, body) {
    pending.createBatch = true
    try {
      return await request(`/bloggers/${subId}/batches`, 'POST', body)
    } catch (err) {
      setError(err)
      throw err
    } finally {
      pending.createBatch = false
    }
  }

  async function listBatches(subId) {
    try {
      const data = await request(`/bloggers/${subId}/batches`)
      batches.value = data.batches || []
      return batches.value
    } catch (err) {
      return setError(err)
    }
  }

  async function getBatch(batchId, isCurrent = () => true) {
    const ticket = ++batchEpoch
    batchLoading.value = true
    try {
      const data = await request(`/batches/${batchId}`)
      if (ticket !== batchEpoch || !isCurrent()) return null
      currentBatch.value = data
      return data
    } catch (err) {
      return ticket === batchEpoch && isCurrent() ? setError(err) : null
    } finally {
      if (ticket === batchEpoch) batchLoading.value = false
    }
  }

  async function batchAction(batchId, action) {
    batchEpoch += 1
    pending.action = action
    try {
      currentBatch.value = await request(`/batches/${batchId}/actions`, 'POST', { action })
      return currentBatch.value
    } catch (err) {
      setError(err)
      throw err
    } finally {
      pending.action = ''
    }
  }

  function startBatchPolling(batchId, onChange) {
    stopBatchPolling()
    batchPoller.start(async current => {
      const batch = await getBatch(batchId, current)
      if (!current()) return false
      if (!batch) return null
      await onChange?.(batch)
      return !['done', 'failed', 'cancelled'].includes(batch.status)
    })
  }

  function stopBatchPolling() {
    batchPoller.stop()
    batchEpoch += 1
    batchLoading.value = false
  }

  function startSyncPolling(hasActive, onChange) {
    syncPoller.start(async current => {
      if (!hasActive()) return false
      const result = await onChange?.()
      if (!current() || !hasActive()) return false
      return result === null ? null : true
    })
  }

  function stopSyncPolling() {
    syncPoller.stop()
  }

  if (getCurrentScope()) {
    onScopeDispose(() => {
      invalidateVideoRequests()
      stopBatchPolling()
      stopSyncPolling()
    })
  }

  return {
    bloggers, bloggersLoading, bloggersError,
    videos, videosTotal, videosLearnedTotal, videosSubtitleTotal, videosMatchedTotal, videosHasMore, videosLoading,
    pages, pagesLoading, batches, currentBatch, batchLoading, pending, error,
    listBloggers, previewBlogger, addBlogger, updateBlogger, removeBlogger,
    getDeletionPreview, syncBlogger, getSyncStatus, cancelSync,
    invalidateVideoRequests, applyVideoPage, listVideos, listPages, createBatch, listBatches, getBatch, batchAction,
    startBatchPolling, stopBatchPolling, startSyncPolling, stopSyncPolling,
  }
}
