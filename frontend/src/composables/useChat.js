import { ref } from 'vue'
import { useAuth } from './useAuth.js'

const API_BASE = '/api'

export function useChat() {
  const { getAuthHeaders, refreshUsage } = useAuth()
  const chatMessages = ref([])
  const isChatStreaming = ref(false)
  const chatError = ref('')

  async function sendQuestion(subtitleContext, question) {
    if (!subtitleContext || !question.trim()) return

    chatMessages.value.push({ role: 'user', content: question.trim() })
    const placeholderIdx = chatMessages.value.length
    chatMessages.value.push({ role: 'assistant', content: '' })

    isChatStreaming.value = true
    chatError.value = ''

    try {
      const history = chatMessages.value
        .filter(m => !m.isPlaceholder)
        .slice(-12, -1)
        .map(m => ({ role: m.role, content: m.content }))

      const response = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ subtitle_text: subtitleContext, question: question.trim(), history }),
      })

      if (!response.ok) {
        const err = await response.json()
        throw new Error(err.detail || '问答失败')
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
            if (event.type === 'text') {
              chatMessages.value[placeholderIdx].content += event.data.text
            } else if (event.type === 'error') {
              chatError.value = event.data.message
            }
          } catch (e) { /* skip */ }
        }
      }
    } catch (e) {
      chatError.value = e.message || '问答失败'
      chatMessages.value[placeholderIdx].content = '[回答失败，请重试]'
    } finally {
      isChatStreaming.value = false
      refreshUsage()
    }
  }

  function resetChat() {
    chatMessages.value = []
    isChatStreaming.value = false
    chatError.value = ''
  }

  return { chatMessages, isChatStreaming, chatError, sendQuestion, resetChat }
}
