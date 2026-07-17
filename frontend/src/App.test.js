import { shallowMount } from '@vue/test-utils'
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

vi.mock('./composables/useSummary.js', () => ({
  useSummary: () => ({
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
    fetchSubtitleText: vi.fn(),
    summarizeVideoStream: vi.fn(),
    summarizeVideo: vi.fn(),
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
    mocks.summaryResult = null
    mocks.summarySubtitleText = ''
    mocks.summaryQaPairs = null
    Element.prototype.scrollIntoView = vi.fn()
  })

  it('reparses when browser navigation changes the workspace URL', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/workspace?url=https%3A%2F%2Fexample.com%2Fone&tab=summary&part=1')
    await router.isReady()
    const wrapper = shallowMount(App, { global: { plugins: [router] } })
    await vi.waitFor(() => expect(mocks.parseVideo).toHaveBeenCalledWith('https://example.com/one'))
    mocks.parseVideo.mockClear()

    await router.push('/workspace?url=https%3A%2F%2Fexample.com%2Ftwo&tab=summary&part=1')

    await vi.waitFor(() => expect(mocks.parseVideo).toHaveBeenCalledWith('https://example.com/two'))
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
        stubs: { ResultWorkspace: false, AiSummary: false },
      },
    })

    await vi.waitFor(() => expect(wrapper.find('.qa-pair-header').exists()).toBe(true))
    await wrapper.find('.sub-tab-btn:last-child').trigger('click')
    await wrapper.find('.qa-pair-header').trigger('click')

    expect(wrapper.find('.qa-pair-answer').attributes('style')).not.toContain('display: none')
    expect(wrapper.find('.qa-pair-answer-content').text()).toContain('视频答案')
    wrapper.unmount()
  })
})
