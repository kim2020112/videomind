import { ref, onUnmounted } from 'vue'
import { useAuth } from './useAuth.js'

const API_BASE = '/api'

export function useDownloader() {
  const { getAuthHeaders, guestId, guestSig } = useAuth()
  const videoInfo = ref(null)
  const formats = ref([])
  const selectedFormat = ref('best')
  const progress = ref(null)
  const downloadHistory = ref([])
  const isParsing = ref(false)
  const taskId = ref(null)
  const subtitles = ref([])
  let ws = null

  async function parseVideo(url) {
    isParsing.value = true
    videoInfo.value = null
    formats.value = []
    selectedFormat.value = 'best'
    progress.value = null

    try {
      const res = await fetch(`${API_BASE}/parse`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ url }),
      })

      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || '解析失败')
      }

      const data = await res.json()
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
    } catch (e) {
      throw e
    } finally {
      isParsing.value = false
    }
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
    const params = new URLSearchParams()
    if (guestId.value && guestSig.value) {
      params.set('guest_id', guestId.value)
      params.set('guest_sig', guestSig.value)
    }
    const query = params.toString() ? `?${params}` : ''
    const wsUrl = `${protocol}//${window.location.host}/ws/download/${tid}${query}`

    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      // 发送下载指令
      ws.send(JSON.stringify({
        url,
        format_id: selectedFormat.value,
        ...extraData,
      }))
      progress.value = { status: 'downloading', percent: 0 }
    }

    ws.onmessage = (event) => {
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
          ws.close()
        } else if (data.status === 'failed') {
          downloadHistory.value.unshift({
            task_id: tid,
            title: videoInfo.value?.title || '未知视频',
            status: 'failed',
            time: Date.now(),
          })
          ws.close()
        }
      } catch (e) {
        // 消息解析失败，忽略
      }
    }

    ws.onerror = () => {
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
    startDownload,
    startDownloadAll,
    startDownloadSelected,
    downloadFile,
    downloadSubtitle,
    translateSubtitle,
    reset,
  }
}
