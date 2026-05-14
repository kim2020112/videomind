import { ref } from 'vue'

const API_BASE = '/api'

export function useSummary() {
  const summaryResult = ref(null)
  const isSummarizing = ref(false)
  const summarizeError = ref('')
  const streamingText = ref('')
  const subtitleText = ref('')
  const isFetchingSubtitle = ref(false)
  const subtitleError = ref('')
  const subtitleInfo = ref(null)
  const mindmapMarkdown = ref('')
  const notesMarkdown = ref('')
  const generationStage = ref('')

  async function fetchSubtitleText(url, lang) {
    isFetchingSubtitle.value = true
    subtitleError.value = ''
    subtitleInfo.value = null

    try {
      const params = new URLSearchParams({ url })
      if (lang) params.set('lang', lang)
      const res = await fetch(`${API_BASE}/subtitle/text?${params}`)
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || '字幕加载失败')
      }
      const data = await res.json()
      subtitleText.value = data.text
      subtitleInfo.value = data
      return data.text
    } catch (e) {
      subtitleError.value = e.message || '字幕加载失败'
      throw e
    } finally {
      isFetchingSubtitle.value = false
    }
  }

  async function summarizeVideoStream(url, lang) {
    isSummarizing.value = true
    summarizeError.value = ''
    // 立即设置空结果让 Tab 栏出现，流式内容填入摘要 Tab
    summaryResult.value = { summary: '', chapters: [], mindmap: { title: '', children: [] } }
    streamingText.value = ''

    try {
      const body = { url }
      if (lang) body.lang = lang

      const response = await fetch(`${API_BASE}/summarize/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (!response.ok) {
        const err = await response.json()
        throw new Error(err.detail || 'AI 总结失败')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))
            switch (event.type) {
              case 'text_start':
                break
              case 'text':
                streamingText.value += event.data.text
                break
              case 'result':
                summaryResult.value = event.data
                break
              case 'progress':
                generationStage.value = event.data.stage || event.data.message || ''
                break
              case 'mindmap':
                mindmapMarkdown.value = event.data.markdown
                generationStage.value = 'mindmap'
                break
              case 'notes_text':
                notesMarkdown.value += event.data.text
                generationStage.value = 'notes'
                break
              case 'notes':
                notesMarkdown.value = event.data.markdown
                generationStage.value = 'notes'
                break
              case 'warn':
                summarizeError.value = event.data.message
                break
              case 'error':
                summarizeError.value = event.data.message
                break
            }
          } catch (e) {
            // 跳过解析失败的事件
          }
        }
      }
    } catch (e) {
      summarizeError.value = e.message || 'AI 总结失败'
    } finally {
      isSummarizing.value = false
    }
  }

  // 保留旧接口（兼容）
  async function summarizeVideo(url, lang) {
    return await summarizeVideoStream(url, lang)
  }

  function resetSummary() {
    summaryResult.value = null
    summarizeError.value = ''
    streamingText.value = ''
    subtitleText.value = ''
    subtitleInfo.value = null
    mindmapMarkdown.value = ''
    notesMarkdown.value = ''
    generationStage.value = ''
    isFetchingSubtitle.value = false
    subtitleError.value = ''
  }

  return {
    summaryResult,
    isSummarizing,
    summarizeError,
    streamingText,
    subtitleText,
    isFetchingSubtitle,
    subtitleError,
    subtitleInfo,
    mindmapMarkdown,
    notesMarkdown,
    generationStage,
    fetchSubtitleText,
    summarizeVideoStream,
    summarizeVideo,
    resetSummary,
  }
}
