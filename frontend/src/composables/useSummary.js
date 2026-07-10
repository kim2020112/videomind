import { ref } from 'vue'
import { useAuth } from './useAuth.js'

const API_BASE = '/api'

export function useSummary() {
  const { getAuthHeaders, refreshUsage } = useAuth()
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
  const notesSections = ref(null)
  const flashcards = ref(null)
  const qaPairs = ref(null)
  const generationStage = ref('')
  const chapters = ref(null)
  const regeneratingMode = ref('')  // '' | 'summary' | 'mindmap' | 'notes' | 'subtitle'
  const subtitleSource = ref('')
  const isPartialSummary = ref(false)
  const whisperEstimate = ref(null)
  const backgroundTask = ref(null)

  let abortController = null

  async function fetchSubtitleText(url, lang) {
    isFetchingSubtitle.value = true
    subtitleError.value = ''
    subtitleInfo.value = null

    try {
      const params = new URLSearchParams({ url })
      if (lang) params.set('lang', lang)
      const res = await fetch(`${API_BASE}/subtitle/text?${params}`, {
        headers: getAuthHeaders(),
        credentials: 'same-origin',
      })
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

  async function summarizeVideoStream(url, lang, force = false, mode = 'full') {
    // 取消上一次未完成的请求
    if (abortController) {
      abortController.abort()
    }
    abortController = new AbortController()

    isSummarizing.value = true
    regeneratingMode.value = mode === 'full' ? '' : mode
    summarizeError.value = ''
    if (mode === 'full') {
      summaryResult.value = { summary: '', chapters: [], mindmap: { title: '', children: [] } }
      streamingText.value = ''
      notesMarkdown.value = ''
      mindmapMarkdown.value = ''
      notesSections.value = null
      flashcards.value = null
      qaPairs.value = null
      chapters.value = null
      isPartialSummary.value = false
      whisperEstimate.value = null
      backgroundTask.value = null
    } else if (mode === 'summary') {
      streamingText.value = ''
      flashcards.value = null
    } else if (mode === 'mindmap') {
      mindmapMarkdown.value = ''
    } else if (mode === 'notes') {
      notesMarkdown.value = ''
      notesSections.value = null
    }

    try {
      const body = { url, force, mode }
      if (lang) body.lang = lang

      const response = await fetch(`${API_BASE}/summarize/stream`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify(body),
        signal: abortController.signal,
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
                streamingText.value = ''
                summaryResult.value = event.data
                isPartialSummary.value = !!event.data.is_partial
                break
              case 'progress':
                generationStage.value = event.data.stage || event.data.message || ''
                if (event.data.source) {
                  subtitleSource.value = event.data.source
                }
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
              case 'notes_structured':
                notesSections.value = event.data.sections
                generationStage.value = 'notes'
                break
              case 'flashcards':
                flashcards.value = event.data
                break
              case 'qa_pairs':
                qaPairs.value = (event.data || []).map(p => ({ ...p, expanded: false }))
                generationStage.value = 'qanda'
                break
              case 'subtitle_text':
                subtitleText.value = event.data.text
                break
              case 'chapters':
                chapters.value = event.data.chapters
                generationStage.value = 'chapters'
                break
              case 'whisper_estimate':
                whisperEstimate.value = event.data
                break
              case 'background_started':
                backgroundTask.value = event.data
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
      if (e.name !== 'AbortError') {
        summarizeError.value = e.message || 'AI 总结失败'
      }
    } finally {
      isSummarizing.value = false
      regeneratingMode.value = ''
      refreshUsage()
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
    notesSections.value = null
    flashcards.value = null
    qaPairs.value = null
    chapters.value = null
    generationStage.value = ''
    regeneratingMode.value = ''
    subtitleSource.value = ''
    isPartialSummary.value = false
    isFetchingSubtitle.value = false
    whisperEstimate.value = null
    backgroundTask.value = null
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
    notesSections,
    flashcards,
    qaPairs,
    chapters,
    generationStage,
    regeneratingMode,
    subtitleSource,
    isPartialSummary,
    whisperEstimate,
    backgroundTask,
    fetchSubtitleText,
    summarizeVideoStream,
    summarizeVideo,
    resetSummary,
  }
}
