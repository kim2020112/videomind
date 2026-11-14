import { flushPromises, shallowMount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import App from './App.vue'
import { createAppRouter } from './router.js'


const mocks = vi.hoisted(() => ({
  parseVideo: vi.fn(),
  resetDownloader: vi.fn(),
  resetSummary: vi.fn(),
  resetChat: vi.fn(),
  resetQa: vi.fn(),
  videoInfo: null,
  summaryResult: null,
  summarySubtitleText: '',
  summaryQaPairs: null,
  fetchSubtitleText: vi.fn(),
  loadWorkspace: vi.fn(),
}))

vi.mock('./composables/useDownloader.js', () => ({
  useDownloader: () => ({
    videoInfo: ref(mocks.videoInfo),
    formats: ref([]),
    selectedFormat: ref('best'),
    progress: ref(null),
    downloadHistory: ref([]),
    subtitles: ref([]),
    parseVideo: mocks.parseVideo,
    startDownload: vi.fn(),
    startDownloadAll: vi.fn(),
    startDownloadSelected: vi.fn(),
    downloadFile: vi.fn(),
    downloadSubtitle: vi.fn(),
    translateSubtitle: vi.fn(),
    reset: mocks.resetDownloader,
  }),
}))

vi.mock('./composables/useAuth.js', () => ({
  useAuth: () => ({
    init: vi.fn().mockResolvedValue(undefined),
    isLoggedIn: ref(true),
    guestSig: ref(''),
  }),
}))

vi.mock('./composables/useTaskPoller.js', () => ({
  useTaskPoller: () => ({
    activeTasks: ref([]),
    activeTaskCount: ref(0),
    startPolling: vi.fn(),
    stopPolling: vi.fn(),
  }),
}))

vi.mock('./composables/useCapabilities.js', () => ({
  useCapabilities: () => ({
    capabilities: ref({ guest_access_enabled: true }),
    loaded: ref(true),
    error: ref(''),
    fetchCapabilities: vi.fn().mockResolvedValue(true),
  }),
}))

vi.mock('./composables/useLearning.js', () => ({
  useLearning: () => ({
    summaryResult: ref(mocks.summaryResult),
    isSummarizing: ref(false),
    summarizeError: ref(''),
    streamingText: ref(''),
    subtitleText: ref(mocks.summarySubtitleText),
    isFetchingSubtitle: ref(false),
    subtitleError: ref(''),
    subtitleInfo: ref(null),
    mindmapMarkdown: ref(''),
    notesMarkdown: ref(''),
    notesSections: ref(null),
    flashcards: ref(null),
    qaPairs: ref(mocks.summaryQaPairs),
    generationStage: ref(''),
    regeneratingMode: ref(''),
    subtitleSource: ref(''),
    isPartialSummary: ref(false),
    whisperEstimate: ref(null),
    backgroundTask: ref(null),
    fetchSubtitleText: mocks.fetchSubtitleText,
    moduleStates: ref({}), workspaceCoverage: ref('empty'), selectedTargets: ref(['summary', 'mindmap', 'notes', 'qa']),
    submitting: ref(false), descriptionSummary: ref(null),
    loadWorkspace: mocks.loadWorkspace, generateLearning: vi.fn(), resumeTask: vi.fn(), cancelTask: vi.fn(),
    resetSummary: mocks.resetSummary,
  }),
}))

vi.mock('./composables/useChat.js', () => ({
  useChat: () => ({
    chatMessages: ref([]),
    isChatStreaming: ref(false),
    chatError: ref(''),
    sendQuestion: vi.fn(),
    resetChat: mocks.resetChat,
  }),
}))

vi.mock('./composables/useQa.js', () => ({
  useQa: () => ({
    qaPairs: ref([]),
    isQaGenerating: ref(false),
    qaError: ref(''),
    generateQa: vi.fn(),
    toggleExpand: vi.fn(),
    resetQa: mocks.resetQa,
  }),
}))

describe('App workspace route restoration', () => {
  beforeEach(() => {
    mocks.parseVideo.mockReset().mockResolvedValue(undefined)
    mocks.videoInfo = null
    mocks.fetchSubtitleText.mockReset()
    mocks.loadWorkspace.mockReset().mockResolvedValue({ subtitle: null, task: null })
    mocks.summaryResult = null
    mocks.summarySubtitleText = ''
    mocks.summaryQaPairs = null
    Element.prototype.scrollIntoView = vi.fn()
  })

  it('keeps a blogger return link across workspace tabs, parts and refresh', async () => {
    const router = createAppRouter(createMemoryHistory())
    const returnTo = '/bloggers/7?q=相机&learned=unlearned&page=2#video-25'
    await router.push({ name: 'workspace', query: { url: 'https://example.com/video', returnTo } })
    const mountApp = () => shallowMount(App, {
      global: { plugins: [router], stubs: { RouterLink: false } },
    })
    let wrapper = mountApp()
    await flushPromises()
    expect(wrapper.find('.workspace-back-link').attributes('href')).toBe(router.resolve(returnTo).href)

    await router.replace({ query: { ...router.currentRoute.value.query, tab: 'download', part: '3' } })
    await flushPromises()
    wrapper.unmount()
    wrapper = mountApp()
    await flushPromises()
    expect(wrapper.find('.workspace-back-link').text()).toContain('返回博主视频列表')
    await wrapper.find('.workspace-back-link').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('blogger-detail')
    expect(router.currentRoute.value.params.id).toBe('7')
    expect(router.currentRoute.value.query).toEqual({ q: '相机', learned: 'unlearned', page: '2' })
    expect(router.currentRoute.value.hash).toBe('#video-25')
    wrapper.unmount()
  })

  it.each(['https://evil.test/bloggers/7', '//evil.test/bloggers/7', '/history', '/bloggers/7/other'])('ignores invalid return destinations: %s', async (returnTo) => {
    const router = createAppRouter(createMemoryHistory())
    await router.push({ name: 'workspace', query: { returnTo } })
    const wrapper = shallowMount(App, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.find('.workspace-back-link').exists()).toBe(false)
    wrapper.unmount()
  })

  it('records the blogger list as the workspace origin when opening a video', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/bloggers/7?q=camera&learned=unlearned&page=2')
    const wrapper = shallowMount(App, { global: { plugins: [router] } })
    await flushPromises()
    wrapper.findComponent({ name: 'BloggerDetailPage' }).vm.$emit('open-workspace', {
      url: 'https://example.com/video', returnTo: '/bloggers/7?q=camera&learned=unlearned&page=2#video-25',
    })
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('workspace')
    expect(router.currentRoute.value.query.returnTo).toBe('/bloggers/7?q=camera&learned=unlearned&page=2#video-25')
    wrapper.unmount()
  })

  it('reparses when browser navigation changes the workspace URL', async () => {
    mocks.videoInfo = { webpage_url: 'https://example.com/video' }
    const router = createAppRouter(createMemoryHistory())
    await router.push('/workspace?url=https%3A%2F%2Fexample.com%2Fone&tab=summary&part=1')
    await router.isReady()
    const wrapper = shallowMount(App, { global: { plugins: [router] } })
    await vi.waitFor(() => expect(mocks.parseVideo).toHaveBeenCalledWith('https://example.com/one'))
    await vi.waitFor(() => expect(mocks.fetchSubtitleText).toHaveBeenCalledWith('https://example.com/video', '', false))
    mocks.fetchSubtitleText.mockClear()
    mocks.parseVideo.mockClear()

    await router.push('/workspace?url=https%3A%2F%2Fexample.com%2Ftwo&tab=summary&part=1')

    await vi.waitFor(() => expect(mocks.parseVideo).toHaveBeenCalledWith('https://example.com/two'))
    await vi.waitFor(() => expect(mocks.fetchSubtitleText).toHaveBeenCalledOnce())
    wrapper.unmount()
  })

  it.each([
    ['explicitly cleared subtitles', { subtitle: null, subtitle_cleared: true, task: null }],
    ['saved subtitles', { subtitle: { text: '已保存字幕' }, task: null }],
    ['an awaiting transcription task', { subtitle: null, task: { status: 'awaiting_confirmation' } }],
  ])('reuses %s without starting another fetch', async (_label, snapshot) => {
    mocks.videoInfo = { webpage_url: 'https://example.com/video' }
    mocks.loadWorkspace.mockResolvedValue(snapshot)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/workspace?url=https%3A%2F%2Fexample.com%2Fvideo')
    await router.isReady()
    const wrapper = shallowMount(App, { global: { plugins: [router] } })
    await vi.waitFor(() => expect(mocks.loadWorkspace).toHaveBeenCalled())
    expect(mocks.fetchSubtitleText).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('toggles answers when generated pairs come from the full summary stream', async () => {
    mocks.videoInfo = { webpage_url: 'https://example.com/video', title: '示例视频', parts: [] }
    mocks.summaryResult = { summary: '视频摘要' }
    mocks.summarySubtitleText = '视频字幕内容'
    mocks.summaryQaPairs = [{ question: '这个视频讲了什么？', answer: '视频答案', expanded: false }]
    window.matchMedia = () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })

    const router = createAppRouter(createMemoryHistory())
    await router.push('/workspace?url=https%3A%2F%2Fexample.com%2Fvideo')
    await router.isReady()
    const wrapper = shallowMount(App, {
      global: {
        plugins: [router],
        renderStubDefaultSlot: true,
        stubs: { ResultWorkspace: false, AiSummary: false, LearningWorkspace: false },
      },
    })

    await vi.waitFor(() => expect(wrapper.find('.qa-pair-header').exists()).toBe(true))
    await wrapper.findAll('.sub-tab-btn').find(button => button.text().includes('精选问答')).trigger('click')
    await wrapper.find('.qa-pair-header').trigger('click')

    expect(wrapper.find('.qa-pair-answer').attributes('style')).not.toContain('display: none')
    expect(wrapper.find('.qa-pair-answer-content').text()).toContain('视频答案')
    wrapper.unmount()
  })
})
