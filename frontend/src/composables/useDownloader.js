import { ref, reactive } from 'vue'

const API_BASE = '/api'

export function useDownloader() {
  const videoInfo = ref(null)
  const formats = ref([])
  const selectedFormat = ref('best')
  const progress = ref(null)
  const downloadHistory = ref([])
  const isParsing = ref(false)
  const taskId = ref(null)
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
        headers: { 'Content-Type': 'application/json' },
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
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, format_id: selectedFormat.value }),
    })
      .then((res) => res.json())
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
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, format_id: selectedFormat.value }),
    })
      .then((res) => res.json())
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
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, format_id: selectedFormat.value }),
    })
      .then((res) => res.json())
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
    const wsUrl = `${protocol}//${window.location.host}/ws/download/${tid}`

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
          })
          ws.close()
        } else if (data.status === 'failed') {
          downloadHistory.value.unshift({
            task_id: tid,
            title: videoInfo.value?.title || '未知视频',
            status: 'failed',
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

  function downloadFile(tid) {
    window.open(`${API_BASE}/files/${tid}`, '_blank')
  }

  function reset() {
    videoInfo.value = null
    formats.value = []
    selectedFormat.value = 'best'
    progress.value = null
    taskId.value = null
    if (ws) {
      ws.close()
      ws = null
    }
  }

  return {
    videoInfo,
    formats,
    selectedFormat,
    progress,
    downloadHistory,
    isParsing,
    taskId,
    parseVideo,
    startDownload,
    startDownloadAll,
    startDownloadSelected,
    downloadFile,
    reset,
  }
}