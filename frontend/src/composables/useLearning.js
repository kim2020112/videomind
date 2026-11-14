import { ref, onScopeDispose } from 'vue'
import { useAuth } from './useAuth.js'

const terminal = new Set(['done', 'partial', 'failed', 'cancelled'])
const active = new Set(['queued', 'downloading', 'transcribing', 'generating'])

// Browsers subscribe to durable work; disposing a page only closes its subscription.
export function useLearning() {
  const { getAuthHeaders, refreshUsage } = useAuth()
  const summaryResult = ref(null)
  const isSummarizing = ref(false)
  const summarizeError = ref('')
  const streamingText = ref('')
  const subtitleText = ref('')
  const isFetchingSubtitle = ref(false)
  const subtitleError = ref('')
  const visitError = ref('')
  const subtitleCleared = ref(false)
  const subtitleInfo = ref(null)
  const mindmapMarkdown = ref('')
  const notesMarkdown = ref('')
  const notesSections = ref(null)
  const flashcards = ref(null)
  const qaPairs = ref([])
  const generationStage = ref('')
  const regeneratingMode = ref('')
  const subtitleSource = ref('')
  const isPartialSummary = ref(false)
  const whisperEstimate = ref(null)
  const backgroundTask = ref(null)
  const moduleStates = ref({})
  const savedTargets = ref([])
  const workspaceCoverage = ref('empty')
  const selectedTargets = ref(['summary', 'mindmap', 'notes', 'qa'])
  const descriptionSummary = ref(null)
  const submitting = ref(false)
  let currentUrl = ''
  let epoch = 0
  let subscription = null
  let lastEventId = 0
  let pendingKey = null
  let summaryDraft = ''
  let notesDraft = ''

  async function request(path, body, signal, method) {
    const response = await fetch(`/api${path}`, {
      method: method || (body ? 'POST' : 'GET'), headers: { ...getAuthHeaders(), ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}), signal,
    })
    if (!response.ok) {
      let error
      try { error = await response.json() } catch { /* generic message below */ }
      throw new Error(typeof error?.detail === 'string' ? error.detail : `请求失败（${response.status}）`)
    }
    return response.json()
  }

  function setTask(task) {
    backgroundTask.value = task
    const running = active.has(task?.status)
    isSummarizing.value = running && Boolean(task?.payload?.targets?.length)
    isFetchingSubtitle.value = running && !subtitleText.value
    if (task?.result?.modules && task?.payload?.input_source !== 'description') {
      for (const [target, state] of Object.entries(task.result.modules)) {
        moduleStates.value[target] = { ...moduleStates.value[target], ...state }
      }
    }
    if (task?.error) {
      if (!task?.payload?.targets?.length) subtitleError.value = task.error
      else summarizeError.value = task.error
    }
  }

  async function readSnapshot(ticket = epoch, incoming) {
    const url = currentUrl
    const snapshot = incoming || await request(`/workspace?${new URLSearchParams({ url })}`)
    if (ticket !== epoch || url !== currentUrl) return null
    const sub = snapshot.subtitle
    subtitleCleared.value = Boolean(snapshot.subtitle_cleared)
    subtitleText.value = sub?.text || ''
    subtitleInfo.value = sub
    subtitleSource.value = sub?.source || ''
    summaryResult.value = snapshot.artifacts.result || null
    mindmapMarkdown.value = snapshot.artifacts.mindmap_markdown || ''
    const running = snapshot.task && active.has(snapshot.task.status)
    notesMarkdown.value = snapshot.artifacts.notes || (running ? notesDraft : '')
    qaPairs.value = (snapshot.artifacts.qa_pairs || []).map(p => ({ ...p, expanded: false }))
    flashcards.value = snapshot.artifacts.result?.flashcards || snapshot.artifacts.flashcards || null
    descriptionSummary.value = snapshot.artifacts.description_summary || null
    savedTargets.value = ['summary', 'mindmap', 'notes', 'qa'].filter(t => snapshot.artifacts[({ summary: 'result', mindmap: 'mindmap_markdown', notes: 'notes', qa: 'qa_pairs' })[t]]?.length || (t === 'summary' && snapshot.artifacts.result?.summary))
    workspaceCoverage.value = snapshot.coverage
    moduleStates.value = snapshot.modules
    setTask(snapshot.task)
    if (!running) {
      notesDraft = ''
      summaryDraft = ''
      streamingText.value = ''
    }
    if (snapshot.task && active.has(snapshot.task.status)) {
      if (notesDraft && !snapshot.artifacts.notes) moduleStates.value.notes.hasExisting = false
      if (summaryDraft && !summaryResult.value?.summary) streamingText.value = summaryDraft
    }
    return snapshot
  }

  function applyEvent(event) {
    const data = event.data || {}
    if (event.type === 'module_status' && backgroundTask.value?.payload?.input_source !== 'description') {
      moduleStates.value[data.target] = { ...moduleStates.value[data.target], ...data, hasExisting: data.target === 'notes' && data.status === 'generating' ? Boolean(notesMarkdown.value) : moduleStates.value[data.target]?.hasExisting }
      regeneratingMode.value = data.status === 'generating' ? data.target : ''
      generationStage.value = data.target
    } else if (event.type === 'module_event') {
      if (data.target === 'summary' && data.type === 'text' && !summaryResult.value?.summary) {
        summaryDraft += data.data.text || ''
        streamingText.value = summaryDraft
      }
      if (data.target === 'notes' && data.type === 'notes_text' && moduleStates.value.notes?.status === 'generating' && !moduleStates.value.notes?.hasExisting) {
        notesDraft += data.data.text || ''
        notesMarkdown.value = notesDraft
      }
    } else if (event.type === 'artifact_saved') {
      if (data.input_source === 'description') descriptionSummary.value = data.content
      else if (data.target === 'summary') { summaryResult.value = data.content; streamingText.value = ''; summaryDraft = '' }
      else if (data.target === 'mindmap') mindmapMarkdown.value = data.content
      else if (data.target === 'notes') { notesMarkdown.value = data.content; notesDraft = '' }
      else if (data.target === 'qa') qaPairs.value = data.content.map(p => ({ ...p, expanded: false }))
      if (data.input_source !== 'description') {
        moduleStates.value[data.target] = { status: 'done', new: true }
        if (!savedTargets.value.includes(data.target)) savedTargets.value = [...savedTargets.value, data.target]
        workspaceCoverage.value = savedTargets.value.length === 4 ? 'complete' : 'partial'
      }
    } else if (event.type === 'task_state' || event.type === 'task_progress') {
      setTask(data)
    }
  }

  async function subscribe(task, ticket = epoch) {
    subscription?.abort()
    const controller = new AbortController()
    subscription = controller
    let completed = false
    while (!completed && ticket === epoch && !controller.signal.aborted) {
      try {
        const response = await fetch(`/api/tasks/${task.task_id}/events?after=${lastEventId}`, {
          headers: getAuthHeaders(), signal: controller.signal,
        })
        if (!response.ok) throw new Error('任务进度连接暂不可用')
        const reader = response.body.getReader()
        let buffer = ''
        const decoder = new TextDecoder()
        try {
          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            if (ticket !== epoch) return
            buffer += decoder.decode(value, { stream: true })
            const frames = buffer.split('\n\n')
            buffer = frames.pop() || ''
            for (const frame of frames) {
              const lines = frame.split('\n')
              const data = lines.find(line => line.startsWith('data: '))
              if (!data) continue
              const event = JSON.parse(data.slice(6))
              const id = Number(lines.find(line => line.startsWith('id: '))?.slice(4) || 0)
              if (id && id <= lastEventId) continue
              if (id) lastEventId = id
              applyEvent(event)
              if (event.type === 'subtitle_ready') await readSnapshot(ticket)
              if (event.type === 'task_state') completed = true
            }
          }
        } finally {
          await reader.cancel().catch(() => {})
          reader.releaseLock?.()
        }
        if (ticket !== epoch || controller.signal.aborted) return
        const snapshot = await readSnapshot(ticket)
        completed = !snapshot?.task || terminal.has(snapshot.task.status) || snapshot.task.status === 'awaiting_confirmation'
        if (completed) {
          streamingText.value = ''
          regeneratingMode.value = ''
          refreshUsage()
        }
      } catch (error) {
        if (controller.signal.aborted || ticket !== epoch) return
        generationStage.value = '连接中断，正在恢复后台进度'
      }
      if (!completed) await new Promise(resolve => {
        const timer = setTimeout(resolve, 2000)
        controller.signal.addEventListener('abort', () => { clearTimeout(timer); resolve() }, { once: true })
      })
    }
  }

  async function loadWorkspace(url) {
    resetSummary()
    currentUrl = url
    const ticket = epoch
    try {
      const snapshot = await readSnapshot(ticket)
      if (snapshot?.task && active.has(snapshot.task.status)) subscribe(snapshot.task, ticket)
      if (snapshot && (snapshot.subtitle?.text || snapshot.coverage !== 'empty' || snapshot.artifacts.description_summary)) {
        try { await request('/workspace/visit', { url }) }
        catch { if (ticket === epoch) visitError.value = '浏览记录暂未保存，返回列表后的标记可能延迟更新。' }
      }
      return ticket === epoch ? snapshot : null
    } catch (error) {
      if (ticket === epoch) summarizeError.value = error.message
    }
  }

  async function clearSubtitle() {
    if (submitting.value || backgroundTask.value && (active.has(backgroundTask.value.status) || backgroundTask.value.status === 'awaiting_confirmation')) return
    const ticket = epoch
    submitting.value = true
    subtitleError.value = ''
    try {
      const snapshot = await request('/workspace/subtitle', { url: currentUrl }, undefined, 'DELETE')
      if (ticket !== epoch) return
      await readSnapshot(ticket, snapshot)
      visitError.value = ''
    } catch (error) {
      if (ticket === epoch) subtitleError.value = error.message
    } finally { if (ticket === epoch) submitting.value = false }
  }

  async function start(path, body) {
    if (submitting.value || backgroundTask.value && (active.has(backgroundTask.value.status) || backgroundTask.value.status === 'awaiting_confirmation')) return
    const ticket = epoch
    const url = currentUrl
    submitting.value = true
    summarizeError.value = ''
    subtitleError.value = ''
    // Retain this key after a network failure; a retry must not create a second operation.
    const signature = JSON.stringify({ path, ...body, url })
    if (pendingKey?.signature !== signature) pendingKey = { signature, key: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}` }
    try {
      const task = await request(path, { ...body, url, request_key: pendingKey.key })
      if (ticket !== epoch) return
      pendingKey = null
      lastEventId = 0
      summaryDraft = ''
      notesDraft = ''
      streamingText.value = ''
      setTask(task)
      for (const target of task.payload?.targets || []) {
        moduleStates.value[target] = { ...moduleStates.value[target], hasExisting: target === 'notes' && Boolean(notesMarkdown.value) }
      }
      subscribe(task, ticket)
    } catch (error) {
      if (ticket === epoch) {
        if (path === '/subtitle/prepare') subtitleError.value = error.message
        else summarizeError.value = error.message
      }
    } finally {
      if (ticket === epoch) submitting.value = false
    }
  }

  function generateLearning(targets = selectedTargets.value, force = false, inputSource = 'subtitle') {
    if (!targets.length) return
    return start('/learning/generate', { targets, force, input_source: inputSource })
  }

  function fetchSubtitleText(url = currentUrl, lang = '', refresh = false) {
    return start('/subtitle/prepare', { lang, refresh_subtitle: refresh })
  }

  async function resumeTask() {
    if (!backgroundTask.value || submitting.value) return
    const ticket = epoch
    submitting.value = true
    try {
      const task = await request(`/tasks/${backgroundTask.value.task_id}/resume`, {})
      if (ticket !== epoch) return
      setTask(task)
      subscribe(task, ticket)
    } catch (error) { if (ticket === epoch) subtitleError.value = error.message }
    finally { if (ticket === epoch) submitting.value = false }
  }

  async function cancelTask() {
    const taskId = backgroundTask.value?.task_id
    const ticket = epoch
    if (!taskId) return
    try {
      await request(`/tasks/${taskId}/cancel`, {})
      if (ticket === epoch) {
        const snapshot = await readSnapshot(ticket)
        if (snapshot?.task && active.has(snapshot.task.status)) subscribe(snapshot.task, ticket)
        else refreshUsage()
      }
    } catch (error) { if (ticket === epoch) summarizeError.value = error.message }
  }

  function resetSummary() {
    epoch += 1
    subscription?.abort()
    subscription = null
    lastEventId = 0
    pendingKey = null
    summaryDraft = ''
    notesDraft = ''
    currentUrl = ''
    for (const state of [summaryResult, subtitleInfo, notesSections, flashcards, backgroundTask, descriptionSummary]) state.value = null
    for (const state of [visitError, summarizeError, streamingText, subtitleText, subtitleError, mindmapMarkdown, notesMarkdown, generationStage, regeneratingMode, subtitleSource]) state.value = ''
    subtitleCleared.value = false
    isSummarizing.value = false
    isFetchingSubtitle.value = false
    submitting.value = false
    qaPairs.value = []
    moduleStates.value = {}
    savedTargets.value = []
    workspaceCoverage.value = 'empty'
  }
  onScopeDispose(() => { epoch += 1; subscription?.abort() })
  return { summaryResult, isSummarizing, summarizeError, streamingText, subtitleText, isFetchingSubtitle,
    subtitleError, visitError, subtitleCleared, clearSubtitle, subtitleInfo, mindmapMarkdown, notesMarkdown, notesSections, flashcards, qaPairs,
    generationStage, regeneratingMode, subtitleSource, isPartialSummary, whisperEstimate, backgroundTask,
    moduleStates, savedTargets, workspaceCoverage, selectedTargets, descriptionSummary, submitting, loadWorkspace, generateLearning,
    resumeTask, cancelTask, fetchSubtitleText, resetSummary }
}
