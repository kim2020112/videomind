import { ref } from 'vue'
import { useAuth } from './useAuth.js'

const API_BASE = '/api'

export function useQa() {
  const { getAuthHeaders, refreshUsage } = useAuth()
  const qaPairs = ref([])
  const isQaGenerating = ref(false)
  const qaError = ref('')

  async function generateQa(subtitleText, videoTitle, url = '', force = false) {
    if (!subtitleText) {
      qaError.value = '请先加载字幕文本'
      return
    }

    qaPairs.value = []
    isQaGenerating.value = true
    qaError.value = ''

    try {
      const response = await fetch(`${API_BASE}/qa/stream`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          subtitle_text: subtitleText,
          video_title: videoTitle || '',
          url: url || '',
          force,
        }),
      })

      if (!response.ok) {
        const err = await response.json()
        throw new Error(err.detail || '问答对生成失败')
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
            if (event.type === 'qa_pairs') {
              qaPairs.value = (event.data || []).map(p => ({ ...p, expanded: false }))
            } else if (event.type === 'error') {
              qaError.value = event.data.message
            }
          } catch (e) { /* skip */ }
        }
      }
    } catch (e) {
      qaError.value = e.message || '问答对生成失败'
    } finally {
      isQaGenerating.value = false
      refreshUsage()
    }
  }

  function toggleExpand(index) {
    if (qaPairs.value[index]) {
      qaPairs.value[index].expanded = !qaPairs.value[index].expanded
    }
  }

  function resetQa() {
    qaPairs.value = []
    isQaGenerating.value = false
    qaError.value = ''
  }

  return { qaPairs, isQaGenerating, qaError, generateQa, toggleExpand, resetQa }
}
