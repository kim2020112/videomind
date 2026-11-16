import { ref, onUnmounted } from 'vue'
import { useAuth } from './useAuth.js'

const API_BASE = '/api'

export function useDownloader() {
  const { getAuthHeaders, getAuthQueryParams } = useAuth()
  const videoInfo = ref(null)
  const formats = ref([])
  const selectedFormat = ref('best')
  const progress = ref(null)
  const downloadHistory = ref([])
  const isParsing = ref(false)
  const isLoadingFormats = ref(false)
  let formatsPromise = null
  let formatsController = null
  const taskId = ref(null)
  const subtitles = ref([])
  let ws = null
  let parseEpoch = 0
  let parseController = null

  async function parseVideo(url) {
    formatsController?.abort()
    formatsPromise = null
    isLoadingFormats.value = false
    const ticket = ++parseEpoch
    parseController?.abort()
    const controller = new AbortController()
    parseController = controller
    const timer = setTimeout(() => controller.abort(), 90000)
    isParsing.value = true
    videoInfo.value = null
    formats.value = []
    subtitles.value = []
    selectedFormat.value = 'best'
    progress.value = null

    try {
      const res = await fetch(`${API_BASE}/parse`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ url, metadata_only: true }),
        signal: controller.signal,
      })

      const data = await res.json().catch(() => null)
      if (ticket !== parseEpoch) return false
      if (!res.ok) {
        const detail = typeof data?.detail === 'string' ? data.detail : null
        throw new Error(detail || (res.status >= 500
          ? '服务暂时不可用，请稍后重试；已有学习资料不会丢失'
          : `解析失败（HTTP ${res.status}），请稍后重试`))
      }
      if (!data || typeof data.title !== 'string' || !data.webpage_url) {
        throw new Error('服务返回的视频信息不完整，请稍后重试')
      }
      // 代理缩略图 URL，绕过防盗链
      if (data.thumbnail) {
        data.thumbnail = `/api/thumbnail?url=${encodeURIComponent(data.thumbnail)}`
      }
      videoInfo.value = data
      formats.value = data.formats || []
      subtitles.value = data.subtitles || []

      // 默认选"最佳画质"选项（is_best = true）
      const bestFmt = data.formats?.find((f) => f.is_best)
      if (bestFmt) {
        selectedFormat.value = bestFmt.format_id
      } else if (data.formats?.length) {
        selectedFormat.value = data.formats[0].format_id
      }
      return true
    } catch (e) {
      if (ticket !== parseEpoch) return false
      if (e.name === 'AbortError') throw new Error('视频解析超时，请稍后重试')
      throw e
    } finally {
      clearTimeout(timer)
      if (ticket === parseEpoch) isParsing.value = false
    }
  }

  function loadDownloadFormats(url) {
    if (formatsPromise) return formatsPromise
    const ticket = parseEpoch
    const controller = new AbortController()
    formatsController = controller
    isLoadingFormats.value = true
    const timer = setTimeout(() => controller.abort(), 90000)
    const pending = (async () => {
      try {
        const res = await fetch(`${API_BASE}/parse`, {
          method: 'POST', headers: getAuthHeaders(), signal: controller.signal,
          body: JSON.stringify({ url, metadata_only: false }),
        })
        const data = await res.json().catch(() => null)
        if (ticket !== parseEpoch || controller.signal.aborted) return false
        if (!res.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : '下载格式暂时不可用，请稍后重试')
        if (!data || !Array.isArray(data.formats) || data.webpage_url !== videoInfo.value?.webpage_url) {
          throw new Error('下载格式返回的视频信息不一致，请重新解析')
        }
        formats.value = data.formats
        selectedFormat.value = data.formats.find(f => f.is_best)?.format_id || data.formats[0]?.format_id || 'best'
        videoInfo.value = { ...videoInfo.value, ...data, thumbnail: videoInfo.value.thumbnail }
        return true
      } catch (error) {
        if (ticket !== parseEpoch) return false
        if (error.name === 'AbortError') throw new Error('下载格式获取超时，请稍后重试')
        throw error
      } finally {
        clearTimeout(timer)
        if (ticket === parseEpoch) { isLoadingFormats.value = false; formatsPromise = null }
      }
    })()
    formatsPromise = pending
    return pending
  }

  function startDownload(url) {
    progress.value = { status: 'pending', percent: 0 }

    // 先创建任务
    fetch(`${API_BASE}/download`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ url, format_id: selectedFormat.value }),
    })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(data.detail || '创建下载任务失败')
        return data
      })
      .then((data) => {
        taskId.value = data.task_id
        connectWebSocket(data.task_id, url, {})
      })
      .catch((e) => {
        progress.value = { status: 'failed', percent: 0, error: e.message }
      })
  }

  function startDownloadSelected(url, selectedParts) {
    progress.value = { status: 'pending', percent: 0 }
    fetch(`${API_BASE}/download`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ url, format_id: selectedFormat.value }),
    })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(data.detail || '创建下载任务失败')
        return data
      })
      .then((data) => {
        taskId.value = data.task_id
        connectWebSocket(data.task_id, url, { concat_parts: true, selected_parts: selectedParts })
      })
      .catch((e) => {
        progress.value = { status: 'failed', percent: 0, error: e.message }
      })
  }

  function startDownloadAll(url) {
    progress.value = { status: 'pending', percent: 0 }

    fetch(`${API_BASE}/download`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ url, format_id: selectedFormat.value }),
    })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(data.detail || '创建下载任务失败')
        return data
      })
      .then((data) => {
        taskId.value = data.task_id
        connectWebSocket(data.task_id, url, { concat_parts: true })
      })
      .catch((e) => {
        progress.value = { status: 'failed', percent: 0, error: e.message }
      })
  }

  function connectWebSocket(tid, url, extraData) {
    // 关闭旧连接
    if (ws) {
      ws.close()
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const params = getAuthQueryParams()
    const query = params.toString() ? `?${params}` : ''
    const wsUrl = `${protocol}//${window.location.host}/ws/download/${tid}${query}`

    const socket = new WebSocket(wsUrl)
    ws = socket

    socket.onopen = () => {
      if (ws !== socket) return
      // 发送下载指令
      socket.send(JSON.stringify({
        url,
        format_id: selectedFormat.value,
        ...extraData,
      }))
      progress.value = { status: 'downloading', percent: 0 }
    }

    socket.onmessage = (event) => {
      if (ws !== socket) return
      try {
        const data = JSON.parse(event.data)
        progress.value = data

        if (data.status === 'completed') {
          downloadHistory.value.unshift({
            task_id: tid,
            title: videoInfo.value?.title || '未知视频',
            status: 'completed',
            time: Date.now(),
          })
          socket.close()
        } else if (data.status === 'failed') {
          downloadHistory.value.unshift({
            task_id: tid,
            title: videoInfo.value?.title || '未知视频',
            status: 'failed',
            time: Date.now(),
          })
          socket.close()
        }
      } catch (e) {
        // 消息解析失败，忽略
      }
    }

    socket.onerror = () => {
      if (ws !== socket) return
      progress.value = { status: 'failed', percent: 0, error: 'WebSocket 连接失败' }
    }
  }

  async function saveBlobResponse(res, fallbackName) {
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || '下载失败')
    }
    const blob = await res.blob()
    const disposition = res.headers.get('Content-Disposition') || ''
    const match = disposition.match(/filename="?([^"]+)"?/i)
    const filename = match ? decodeURIComponent(match[1]) : fallbackName
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(objectUrl)
  }

  async function downloadFile(tid) {
    const res = await fetch(`${API_BASE}/files/${tid}`, {
      headers: getAuthHeaders(),
      credentials: 'same-origin',
    })
    await saveBlobResponse(res, 'download')
  }

  async function downloadSubtitle(url, lang, isAuto) {
    const params = new URLSearchParams({ url, lang, auto: isAuto })
    const res = await fetch(`${API_BASE}/subtitle?${params}`, {
      headers: getAuthHeaders(),
      credentials: 'same-origin',
    })
    await saveBlobResponse(res, `subtitle.${lang}.txt`)
  }

  async function translateSubtitle(url, lang, isAuto, targetLang) {
    const params = new URLSearchParams({ url, lang, auto: isAuto, target: targetLang })
    const res = await fetch(`${API_BASE}/subtitle/translate?${params}`, {
      headers: getAuthHeaders(),
      credentials: 'same-origin',
    })
    await saveBlobResponse(res, `subtitle.${lang}.${targetLang}.txt`)
  }

  function reset() {
    ++parseEpoch
    formatsController?.abort()
    formatsPromise = null
    isLoadingFormats.value = false
    parseController?.abort()
    isParsing.value = false
    videoInfo.value = null
    formats.value = []
    selectedFormat.value = 'best'
    progress.value = null
    taskId.value = null
    subtitles.value = []
    if (ws) {
      ws.close()
      ws = null
    }
  }

  onUnmounted(() => {
    ++parseEpoch
    formatsController?.abort()
    formatsPromise = null
    isLoadingFormats.value = false
    parseController?.abort()
    if (ws) {
      ws.close()
      ws = null
    }
  })

  return {
    videoInfo,
    formats,
    selectedFormat,
    progress,
    downloadHistory,
    isParsing,
    taskId,
    subtitles,
    parseVideo,
    loadDownloadFormats,
    isLoadingFormats,
    startDownload,
    startDownloadAll,
    startDownloadSelected,
    downloadFile,
    downloadSubtitle,
    translateSubtitle,
    reset,
  }
}
