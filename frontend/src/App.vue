<script setup>
import { ref, computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDownloader } from './composables/useDownloader.js'
import NavBar from './components/NavBar.vue'
import HeroSection from './components/HeroSection.vue'
import FeaturesSection from './components/FeaturesSection.vue'
import FooterSection from './components/FooterSection.vue'
import AiSummary from './components/AiSummary.vue'
import ResultWorkspace from './components/ResultWorkspace.vue'
import DesktopWorkspace from './components/DesktopWorkspace.vue'
import VideoSidebar from './components/VideoSidebar.vue'
import AiWorkspace from './components/AiWorkspace.vue'
import VideoContextPanel from './components/VideoContextPanel.vue'
import DownloadTools from './components/DownloadTools.vue'
import DownloadHistoryPanel from './components/DownloadHistoryPanel.vue'
import TaskProgressDock from './components/TaskProgressDock.vue'
import { useSummary } from './composables/useSummary.js'
import { useChat } from './composables/useChat.js'
import { useQa } from './composables/useQa.js'
import { useAuth } from './composables/useAuth.js'
import { useTaskPoller } from './composables/useTaskPoller.js'
import { useCapabilities } from './composables/useCapabilities.js'
import { formatBytes } from './utils/resultFormatters.js'
import { canMarkPartCached, markPartCached } from './utils/multipartState.js'

const HistoryPage = defineAsyncComponent(() => import('./components/HistoryPage.vue'))
const VideoPlayerModal = defineAsyncComponent(() => import('./components/VideoPlayerModal.vue'))
const LoginModal = defineAsyncComponent(() => import('./components/LoginModal.vue'))

const route = useRoute()
const router = useRouter()

const { init: initAuth, isLoggedIn, guestSig } = useAuth()
const { activeTasks, activeTaskCount, startPolling, stopPolling } = useTaskPoller()
const {
  capabilities,
  loaded: capabilitiesLoaded,
  error: capabilitiesError,
  fetchCapabilities,
} = useCapabilities()

onMounted(async () => {
  await Promise.all([initAuth(), fetchCapabilities()])
  if (isLoggedIn.value || guestSig.value) startPolling()
  await restoreRouteState()
})
onUnmounted(() => stopPolling())

const {
  videoInfo,
  formats,
  selectedFormat,
  progress,
  downloadHistory,
  subtitles,
  parseVideo,
  startDownload,
  startDownloadAll,
  startDownloadSelected,
  downloadFile,
  downloadSubtitle,
  translateSubtitle,
  reset,
} = useDownloader()

const url = ref('')
const error = ref('')
const loading = ref(false)
const selectedPartIndices = ref([])
const translateTargetLang = ref('zh-Hans')
const activeTab = ref('summary')
const currentSummarizePart = ref(1)
const showLogin = ref(false)
const pendingParse = ref(false)
const resultAnchor = ref(null)

// 多P视频：当前总结的分P URL（保留 ?p=N）
const summarizeUrl = computed(() => {
  if (!videoInfo.value?.parts || videoInfo.value.parts.length <= 1) {
    return videoInfo.value?.webpage_url || url.value
  }
  const bvMatch = (videoInfo.value.webpage_url || '').match(/(BV\w+)/)
  if (!bvMatch) return videoInfo.value?.webpage_url || url.value
  const p = currentSummarizePart.value
  if (p <= 1) return `https://www.bilibili.com/video/${bvMatch[1]}`
  return `https://www.bilibili.com/video/${bvMatch[1]}?p=${p}`
})
const showSubtitles = ref(false)
const showFullDescription = ref(false)
const isHomeRoute = computed(() => route.name === 'home')
const isHistoryRoute = computed(() => route.name === 'history')
const isWorkspaceRoute = computed(() => route.name === 'workspace' || route.name === 'history-detail')
const currentView = computed(() => isHistoryRoute.value ? 'history' : 'home')
const canStart = computed(() => isLoggedIn.value || capabilities.value.guest_access_enabled)
const requiresLogin = computed(() => capabilitiesLoaded.value && !canStart.value)
const serviceChecking = computed(() => !capabilitiesLoaded.value)
const desktopSidebarCollapsed = ref(false)

// 视频播放 Modal
const showVideoModal = ref(false)
const videoStreamUrl = ref('')
const videoCurrentTime = ref(0)
const videoPlayerRef = ref(null)

function openVideoModal() {
  const su = videoInfo.value?.stream_url
  if (!su) return
  videoStreamUrl.value = su
  showVideoModal.value = true
}

function handleSeekVideo(seconds) {
  if (!showVideoModal.value) {
    openVideoModal()
    nextTick(() => {
      setTimeout(() => videoPlayerRef.value?.seekTo(seconds), 300)
    })
  } else {
    videoPlayerRef.value?.seekTo(seconds)
  }
}

function onVideoSeek(time) {
  videoCurrentTime.value = time
}

async function goHome() {
  await router.push({ name: 'home' })
}

async function toggleHistory() {
  await router.push({ name: isHistoryRoute.value ? 'home' : 'history' })
}

function requestLogin({ continueParse = false } = {}) {
  pendingParse.value = continueParse
  showLogin.value = true
}

async function handleAuthenticated() {
  showLogin.value = false
  startPolling()
  if (!pendingParse.value) return
  pendingParse.value = false
  await nextTick()
  await handleParse()
}

async function handleSelectHistory(item) {
  url.value = item.url
  await router.push({
    name: 'history-detail',
    params: { urlHash: item.url_hash || item.id },
    query: { url: item.url, tab: 'summary', part: '1' },
  })
  await handleParse({ syncRoute: false })
  if (videoInfo.value && !error.value) {
    handleSummarize(false)
  }
}

async function restoreRouteState() {
  const queryUrl = typeof route.query.url === 'string' ? route.query.url : ''
  if (queryUrl) url.value = queryUrl
  if (route.query.tab === 'download' || route.query.tab === 'summary') {
    activeTab.value = route.query.tab
  }
  const part = Number.parseInt(route.query.part, 10)
  if (Number.isInteger(part) && part > 0) currentSummarizePart.value = part
  if (isWorkspaceRoute.value && queryUrl && canStart.value) {
    await handleParse({ syncRoute: false })
  }
}

async function syncWorkspaceRoute({ replace = false } = {}) {
  if (!url.value.trim()) return
  const target = {
    name: route.name === 'history-detail' ? 'history-detail' : 'workspace',
    params: route.name === 'history-detail' ? route.params : undefined,
    query: {
      ...route.query,
      url: url.value.trim(),
      tab: activeTab.value,
      part: String(currentSummarizePart.value),
    },
  }
  await (replace ? router.replace(target) : router.push(target))
}

async function scrollToResult() {
  await nextTick()
  resultAnchor.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}


const {
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
  qaPairs: summaryQaPairs,
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
} = useSummary()

const {
  chatMessages,
  isChatStreaming,
  chatError,
  sendQuestion,
  resetChat,
} = useChat()

const {
  qaPairs,
  isQaGenerating,
  qaError,
  generateQa,
  resetQa,
} = useQa()

const displayQaPairs = computed(() => {
  if (qaPairs.value.length > 0) return qaPairs.value
  return summaryQaPairs.value || []
})

// 精选问答可能来自完整总结或单独生成，展开状态必须作用于当前展示的数据源。
function toggleQaExpand(index) {
  const pair = displayQaPairs.value[index]
  if (pair) {
    pair.expanded = !pair.expanded
  }
}

const liveBackgroundTask = computed(() => {
  if (!backgroundTask.value?.task_id) return backgroundTask.value
  return activeTasks.value.find(task => task.task_id === backgroundTask.value.task_id) || backgroundTask.value
})

let backgroundTaskSeenActive = false
watch(() => backgroundTask.value?.task_id, () => {
  backgroundTaskSeenActive = false
})
watch(activeTasks, tasks => {
  const taskId = backgroundTask.value?.task_id
  if (!taskId) return
  if (tasks.some(task => task.task_id === taskId)) {
    backgroundTaskSeenActive = true
  } else if (backgroundTaskSeenActive) {
    backgroundTask.value = null
    backgroundTaskSeenActive = false
  }
})

watch([isLoggedIn, guestSig], ([loggedIn, signature]) => {
  if (loggedIn || signature) startPolling()
  else stopPolling()
})

watch(activeTab, (tab) => {
  if (!isWorkspaceRoute.value || route.query.tab === tab) return
  syncWorkspaceRoute({ replace: true })
})

watch(currentSummarizePart, (part) => {
  if (!isWorkspaceRoute.value || route.query.part === String(part)) return
  syncWorkspaceRoute({ replace: true })
})

watch(() => route.query.tab, (tab) => {
  if (tab === 'summary' || tab === 'download') activeTab.value = tab
})

watch(() => route.query.part, (partValue) => {
  const part = Number.parseInt(partValue, 10)
  if (Number.isInteger(part) && part > 0) currentSummarizePart.value = part
})

watch(() => route.query.url, async (routeUrl) => {
  if (!isWorkspaceRoute.value || typeof routeUrl !== 'string' || !routeUrl) return
  if (routeUrl === url.value) return
  await restoreRouteState()
})

async function handleSummarize(force = false) {
  if (!videoInfo.value) return
  try {
    await summarizeVideoStream(summarizeUrl.value, null, force, 'full')
    if (canMarkPartCached({
      summaryResult: summaryResult.value,
      backgroundTask: backgroundTask.value,
      summaryError: summarizeError.value,
    }) && videoInfo.value?.parts?.length) {
      videoInfo.value = {
        ...videoInfo.value,
        parts: markPartCached(videoInfo.value.parts, currentSummarizePart.value),
      }
    }
  } catch (e) { /* handled by useSummary */ }
}

async function handleRegenerateSummary() {
  if (!videoInfo.value) return
  try {
    await summarizeVideoStream(summarizeUrl.value, null, true, 'summary')
  } catch (e) { /* handled by useSummary */ }
}

async function handleRegenerateMindmap() {
  if (!videoInfo.value) return
  try {
    await summarizeVideoStream(summarizeUrl.value, null, true, 'mindmap')
  } catch (e) { /* handled by useSummary */ }
}

async function handleRegenerateNotes() {
  if (!videoInfo.value) return
  try {
    await summarizeVideoStream(summarizeUrl.value, null, true, 'notes')
  } catch (e) { /* handled by useSummary */ }
}

async function handleRegenerateSubtitle() {
  if (!videoInfo.value) return
  try {
    await summarizeVideoStream(summarizeUrl.value, null, true, 'subtitle')
  } catch (e) { /* handled by useSummary */ }
}

async function handleFetchSubtitle() {
  if (!videoInfo.value) return
  try {
    await fetchSubtitleText(summarizeUrl.value)
  } catch (e) { /* handled by useSummary */ }
}

async function switchSummarizePart(partIndex) {
  if (partIndex === currentSummarizePart.value) return
  currentSummarizePart.value = partIndex
  // 更新 URL 以同步视频信息卡片和分P列表高亮
  const bvMatch = (videoInfo.value?.webpage_url || '').match(/(BV\w+)/)
  if (bvMatch) {
    if (partIndex <= 1) {
      url.value = `https://www.bilibili.com/video/${bvMatch[1]}`
    } else {
      url.value = `https://www.bilibili.com/video/${bvMatch[1]}?p=${partIndex}`
    }
  }
  activeTab.value = 'summary'
  // 清除旧分P的字幕文本，避免显示上一分P的内容
  subtitleText.value = ''
  resetQa()
  await handleSummarize(false)
  // 总结完成后自动获取当前分P的字幕
  fetchSubtitleText(summarizeUrl.value).catch(() => {})
}

function handleSendQuestion(question) {
  sendQuestion(subtitleText.value, question)
}

function handleGenerateQa() {
  generateQa(subtitleText.value, videoInfo.value?.title || '', summarizeUrl.value, false)
}

function handleRegenerateQa() {
  generateQa(subtitleText.value, videoInfo.value?.title || '', summarizeUrl.value, true)
}

// 选中分P的总时长（秒）
const selectedPartsTotalDuration = computed(() => {
  if (!videoInfo.value?.parts || selectedPartIndices.value.length === 0) return null
  const selectedSet = new Set(selectedPartIndices.value)
  let total = 0
  for (const part of videoInfo.value.parts) {
    if (selectedSet.has(part.index) && part.duration) {
      total += part.duration
    }
  }
  return total > 0 ? total : null
})

// 根据选中分P动态调整清晰度列表中的文件大小
// 后端的 filesize 是整个视频的大小，需要按选中分P的时长比例调整
const displayFormats = computed(() => {
  const hasParts = videoInfo.value?.parts && videoInfo.value.parts.length > 1
  if (!hasParts) return formats.value

  const videoDuration = videoInfo.value?.duration
  if (!videoDuration) return formats.value

  // 选中分P的总时长；未选中时用当前分P的时长
  let targetDuration = selectedPartsTotalDuration.value
  if (!targetDuration) {
    const current = videoInfo.value.parts.find(p => p.index === currentPart.value)
    targetDuration = current?.duration || null
  }
  if (!targetDuration) return formats.value

  return formats.value.map(f => {
    if (!f.filesize) return f
    return {
      ...f,
      adjusted_filesize_str: formatBytes(Math.round(f.filesize / videoDuration * targetDuration)),
    }
  })
})

const selectedFormatDetail = computed(() => formats.value.find(f => f.format_id === selectedFormat.value))

const currentPart = computed(() => {
  const m = url.value.match(/[?&]p=(\d+)/)
  return m ? parseInt(m[1]) : 1
})

// 当前总结分P的显示信息（时长、标题）
const currentSummarizePartInfo = computed(() => {
  if (!videoInfo.value?.parts || videoInfo.value.parts.length <= 1) return null
  return videoInfo.value.parts.find(p => p.index === currentSummarizePart.value) || null
})

const isAllPartsSelected = computed(() =>
  videoInfo.value?.parts?.length > 0 &&
  selectedPartIndices.value.length === videoInfo.value.parts.length
)

function handleDownloadSubtitle(sub) {
  downloadSubtitle(videoInfo.value.webpage_url, sub.lang, sub.is_auto)
}

function handleTranslateSubtitle(sub) {
  translateSubtitle(videoInfo.value.webpage_url, sub.lang, sub.is_auto, translateTargetLang.value)
}

function togglePartSelection(index) {
  const i = selectedPartIndices.value.indexOf(index)
  if (i === -1) {
    selectedPartIndices.value = [...selectedPartIndices.value, index]
  } else {
    selectedPartIndices.value = selectedPartIndices.value.filter(x => x !== index)
  }
}

function handleSelectAll() {
  if (isAllPartsSelected.value) {
    selectedPartIndices.value = []
  } else {
    selectedPartIndices.value = videoInfo.value.parts.map(p => p.index)
  }
}

function handleLogout() {
  url.value = ''
  error.value = ''
  loading.value = false
  reset()
  resetSummary()
  resetChat()
  resetQa()
  activeTab.value = 'summary'
  showSubtitles.value = false
  showFullDescription.value = false
  selectedPartIndices.value = []
  pendingParse.value = false
  stopPolling()
  router.push({ name: 'home' })
}

async function handleParse({ syncRoute = true } = {}) {
  if (!url.value.trim()) return
  if (!canStart.value) {
    requestLogin({ continueParse: true })
    return
  }
  if (syncRoute) await syncWorkspaceRoute()
  error.value = ''
  loading.value = true
  selectedPartIndices.value = []
  activeTab.value = 'summary'
  currentSummarizePart.value = 1
  resetSummary()
  resetChat()
  resetQa()
  reset()
  showSubtitles.value = false
  showFullDescription.value = false
  try {
    await parseVideo(url.value.trim())
    // 从 URL 中检测分P编号，设置 AI 总结的当前P
    const pMatch = url.value.match(/[?&]p=(\d+)/)
    if (pMatch) {
      currentSummarizePart.value = parseInt(pMatch[1])
    }
    await syncWorkspaceRoute({ replace: true })
  } catch (e) {
    error.value = e.message || '解析失败，请检查链接是否有效'
  } finally {
    loading.value = false
    await scrollToResult()
  }
}

async function handlePartSelect(part) {
  const bvMatch = (videoInfo.value?.webpage_url || '').match(/(BV\w+)/)
  if (!bvMatch) return
  const partUrl = `https://www.bilibili.com/video/${bvMatch[1]}?p=${part.index}`
  url.value = partUrl
  error.value = ''
  loading.value = true
  selectedPartIndices.value = []
  reset()
  try {
    await parseVideo(partUrl)
  } catch (e) {
    error.value = e.message || '解析失败'
  } finally {
    loading.value = false
  }
}

function handleDownloadSelected() {
  if (!videoInfo.value || selectedPartIndices.value.length === 0) return
  const bvMatch = (videoInfo.value.webpage_url || '').match(/(BV\w+)/)
  if (!bvMatch) return
  startDownloadSelected(`https://www.bilibili.com/video/${bvMatch[1]}`, [...selectedPartIndices.value])
}

function handleDownloadAll() {
  if (!videoInfo.value) return
  const bvMatch = (videoInfo.value.webpage_url || '').match(/(BV\w+)/)
  if (!bvMatch) return
  startDownloadAll(`https://www.bilibili.com/video/${bvMatch[1]}`)
}

function handleDownload() {
  if (!videoInfo.value) return
  const bvMatch = (videoInfo.value.webpage_url || '').match(/(BV\w+)/)
  if (!bvMatch) {
    // 非B站视频，直接下载
    startDownload(videoInfo.value.webpage_url)
    return
  }
  const baseUrl = `https://www.bilibili.com/video/${bvMatch[1]}`
  if (selectedPartIndices.value.length > 0) {
    // 有选中的分P，下载选中的分P（合并）
    startDownloadSelected(baseUrl, [...selectedPartIndices.value])
  } else if (videoInfo.value.parts && videoInfo.value.parts.length > 1) {
    // 多P视频但未选中，下载当前分P
    const partMatch = url.value.match(/[?&]p=(\d+)/)
    const partNum = partMatch ? parseInt(partMatch[1]) : 1
    startDownloadSelected(baseUrl, [partNum])
  } else {
    startDownload(videoInfo.value.webpage_url)
  }
}

function handleDownloadFile(taskId) {
  downloadFile(taskId)
}

function handleUrlChange(value) {
  url.value = value
}

</script>

<template>
  <div class="app-container">
    <NavBar
      :currentView="currentView"
      :activeTaskCount="activeTaskCount"
      @toggle-history="toggleHistory"
      @logout="handleLogout"
      @go-home="goHome"
      @request-login="requestLogin()"
    />

    <!-- 学习历史页 -->
    <HistoryPage v-if="isHistoryRoute" :activeTasks="activeTasks" @select-item="handleSelectHistory" />

    <!-- 首页内容 -->
    <template v-if="!isHistoryRoute">

    <HeroSection
      v-model:url="url"
      :loading="loading"
      :compact="isWorkspaceRoute"
      :requiresLogin="requiresLogin"
      :serviceChecking="serviceChecking"
      :serviceError="capabilitiesError"
      @parse="handleParse()"
      @request-login="requestLogin({ continueParse: true })"
      @retry-capabilities="fetchCapabilities"
    />

    <!-- Results Section -->
    <div ref="resultAnchor">
    <ResultWorkspace v-if="isWorkspaceRoute && (videoInfo || error)">
      <template #desktop>
        <div class="desktop-results-container">
          <div v-if="error" class="error-card">
            <svg class="error-icon" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
            </svg>
            <span>{{ error }}</span>
          </div>

          <DesktopWorkspace v-if="videoInfo" :sidebarCollapsed="desktopSidebarCollapsed">
            <template #sidebar>
              <VideoSidebar>
                <VideoContextPanel
                  variant="sidebar"
                  :videoInfo="videoInfo"
                  :currentPartInfo="currentSummarizePartInfo"
                  :collapsed="desktopSidebarCollapsed"
                  :showFullDescription="showFullDescription"
                  @open-video="openVideoModal"
                  @update:collapsed="desktopSidebarCollapsed = $event"
                  @update:show-full-description="showFullDescription = $event"
                />
                <DownloadTools
                  v-if="!desktopSidebarCollapsed"
                  variant="sidebar"
                  :videoInfo="videoInfo"
                  :formats="displayFormats"
                  :selectedFormat="selectedFormat"
                  :selectedFormatDetail="selectedFormatDetail"
                  :selectedPartIndices="selectedPartIndices"
                  :currentPart="currentPart"
                  :isAllPartsSelected="isAllPartsSelected"
                  :subtitles="subtitles"
                  :showSubtitles="showSubtitles"
                  :translateTargetLang="translateTargetLang"
                  :progress="progress"
                  @select-format="selectedFormat = $event"
                  @toggle-part="togglePartSelection"
                  @select-all-parts="handleSelectAll"
                  @download="handleDownload"
                  @download-selected="handleDownloadSelected"
                  @download-all="handleDownloadAll"
                  @download-subtitle="handleDownloadSubtitle"
                  @translate-subtitle="handleTranslateSubtitle"
                  @update:show-subtitles="showSubtitles = $event"
                  @update:translate-target-lang="translateTargetLang = $event"
                />
              </VideoSidebar>
            </template>

            <template #main>
              <AiWorkspace>
                <div class="video-card desktop-ai-card">
                  <AiSummary
                    :result="summaryResult"
                    :loading="isSummarizing"
                    :regeneratingMode="regeneratingMode"
                    :subtitleSource="subtitleSource"
                    :error="summarizeError"
                    :streamingText="streamingText"
                    :subtitleText="subtitleText"
                    :isFetchingSubtitle="isFetchingSubtitle"
                    :subtitleError="subtitleError"
                    :chatMessages="chatMessages"
                    :isChatStreaming="isChatStreaming"
                    :chatError="chatError"
                    :subtitleInfo="subtitleInfo"
                    :isPartialSummary="isPartialSummary"
                    :whisperEstimate="whisperEstimate"
                    :backgroundTask="liveBackgroundTask"
                    :videoTitle="videoInfo?.title || ''"
                    :mindmapMarkdown="mindmapMarkdown"
                    :notesMarkdown="notesMarkdown"
                    :notesSections="notesSections"
                    :flashcards="flashcards"
                    :generationStage="generationStage"
                    :multiParts="videoInfo?.parts?.length > 1 ? videoInfo.parts : []"
                    :currentSummarizePart="currentSummarizePart"
                    :onSummarize="handleSummarize"
                    :onRegenerateSummary="handleRegenerateSummary"
                    :onRegenerateMindmap="handleRegenerateMindmap"
                    :onRegenerateNotes="handleRegenerateNotes"
                    :onRegenerateSubtitle="handleRegenerateSubtitle"
                    :onFetchSubtitle="handleFetchSubtitle"
                    :onSendQuestion="handleSendQuestion"
                    :onGenerateQa="handleGenerateQa"
                    :onRegenerateQa="handleRegenerateQa"
                    :qaPairs="displayQaPairs"
                    :isQaGenerating="isQaGenerating"
                    :qaError="qaError"
                    :onToggleQaExpand="toggleQaExpand"
                    :onSwitchPart="switchSummarizePart"
                    :onSeekVideo="handleSeekVideo"
                    :currentVideoTime="videoCurrentTime"
                  />
                </div>

                <DownloadHistoryPanel
                  :history="downloadHistory"
                  desktop
                  @download-file="handleDownloadFile"
                />
              </AiWorkspace>
            </template>
          </DesktopWorkspace>
        </div>
      </template>

      <template #mobile>
      <div class="results-container">
        <!-- Error Message -->
        <div v-if="error" class="error-card">
          <svg class="error-icon" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
          </svg>
          <span>{{ error }}</span>
        </div>

        <VideoContextPanel
          v-if="videoInfo"
          :videoInfo="videoInfo"
          :currentPartInfo="currentSummarizePartInfo"
          collapsible
          :showFullDescription="showFullDescription"
          @open-video="openVideoModal"
          @update:show-full-description="showFullDescription = $event"
        />

        <div v-if="videoInfo" class="video-card result-content-card">
          <div class="tab-bar">
            <button class="tab-button" :class="{ active: activeTab === 'summary' }" @click="activeTab = 'summary'">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="tab-icon"><path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" /></svg>
              AI 总结
            </button>
            <button class="tab-button" :class="{ active: activeTab === 'download' }" @click="activeTab = 'download'">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="tab-icon"><path stroke-linecap="round" stroke-linejoin="round" d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 11l5 5m0 0l5-5m-5 5V3" /></svg>
              视频下载
            </button>
          </div>

          <!-- Tab: 下载区 -->
          <div v-show="activeTab === 'download'">
            <DownloadTools
              :videoInfo="videoInfo"
              :formats="displayFormats"
              :selectedFormat="selectedFormat"
              :selectedFormatDetail="selectedFormatDetail"
              :selectedPartIndices="selectedPartIndices"
              :currentPart="currentPart"
              :isAllPartsSelected="isAllPartsSelected"
              :subtitles="subtitles"
              :showSubtitles="showSubtitles"
              :translateTargetLang="translateTargetLang"
              :progress="progress"
              @select-format="selectedFormat = $event"
              @toggle-part="togglePartSelection"
              @select-all-parts="handleSelectAll"
              @download="handleDownload"
              @download-selected="handleDownloadSelected"
              @download-all="handleDownloadAll"
              @download-subtitle="handleDownloadSubtitle"
              @translate-subtitle="handleTranslateSubtitle"
              @update:show-subtitles="showSubtitles = $event"
              @update:translate-target-lang="translateTargetLang = $event"
            />
          </div><!-- end v-show activeTab === 'download' -->

          <!-- Tab: AI 总结 -->
          <div v-show="activeTab === 'summary'">
            <AiSummary
              :result="summaryResult"
              :loading="isSummarizing"
              :regeneratingMode="regeneratingMode"
              :subtitleSource="subtitleSource"
              :error="summarizeError"
              :streamingText="streamingText"
              :subtitleText="subtitleText"
              :isFetchingSubtitle="isFetchingSubtitle"
              :subtitleError="subtitleError"
              :chatMessages="chatMessages"
              :isChatStreaming="isChatStreaming"
              :chatError="chatError"
              :subtitleInfo="subtitleInfo"
              :isPartialSummary="isPartialSummary"
              :whisperEstimate="whisperEstimate"
              :backgroundTask="liveBackgroundTask"
              :videoTitle="videoInfo?.title || ''"
              :mindmapMarkdown="mindmapMarkdown"
              :notesMarkdown="notesMarkdown"
              :notesSections="notesSections"
              :flashcards="flashcards"
              :generationStage="generationStage"
              :multiParts="videoInfo?.parts?.length > 1 ? videoInfo.parts : []"
              :currentSummarizePart="currentSummarizePart"
              :onSummarize="handleSummarize"
              :onRegenerateSummary="handleRegenerateSummary"
              :onRegenerateMindmap="handleRegenerateMindmap"
              :onRegenerateNotes="handleRegenerateNotes"
              :onRegenerateSubtitle="handleRegenerateSubtitle"
              :onFetchSubtitle="handleFetchSubtitle"
              :onSendQuestion="handleSendQuestion"
              :onGenerateQa="handleGenerateQa"
              :onRegenerateQa="handleRegenerateQa"
              :qaPairs="displayQaPairs"
              :isQaGenerating="isQaGenerating"
              :qaError="qaError"
              :onToggleQaExpand="toggleQaExpand"
              :onSwitchPart="switchSummarizePart"
              :onSeekVideo="handleSeekVideo"
              :currentVideoTime="videoCurrentTime"
            />
          </div>
        </div>

        <DownloadHistoryPanel
          :history="downloadHistory"
          @download-file="handleDownloadFile"
        />
      </div>
      </template>
    </ResultWorkspace>
    </div>

    </template>

    <FeaturesSection v-if="isHomeRoute" />
    <FooterSection v-if="isHomeRoute" />
    <LoginModal
      :visible="showLogin"
      @close="showLogin = false"
      @authenticated="handleAuthenticated"
    />
    <VideoPlayerModal
      ref="videoPlayerRef"
      :visible="showVideoModal"
      :streamUrl="videoStreamUrl"
      :videoTitle="videoInfo?.title || ''"
      :videoUrl="videoInfo?.webpage_url || ''"
      @close="showVideoModal = false"
      @seek="onVideoSeek"
    />
    <TaskProgressDock :tasks="activeTasks" @open-history="router.push({ name: 'history' })" />
  </div>
</template>

<style scoped>
.app-container {
  min-height: 100vh;
  background: var(--bg-primary);
}

.results-container {
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.desktop-results-container {
  width: 100%;
}

.video-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 2rem;
  backdrop-filter: blur(12px);
}

.desktop-ai-card {
  padding: 1.75rem;
}

.error-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: var(--radius);
  color: #FCA5A5;
  font-size: 0.9375rem;
}

.error-icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
}

.feature-warning {
  max-width: 1100px;
  margin: 0 auto;
  padding: 0.75rem 1.25rem;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.2);
  border-radius: var(--radius);
  color: #FCD34D;
  font-size: 0.875rem;
  text-align: center;
}

.tab-bar {
  display: flex;
  gap: 0.25rem;
  margin-bottom: 1.5rem;
  padding: 0.25rem;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 10px;
  border: 1px solid var(--border);
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}

.tab-bar::-webkit-scrollbar {
  display: none;
}

.tab-button {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  padding: 0.625rem 1rem;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: var(--text-muted);
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.tab-button:hover {
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.05);
}

.tab-button.active {
  background: rgba(59, 130, 246, 0.15);
  color: #93C5FD;
}

.tab-icon {
  width: 16px;
  height: 16px;
}

@media (max-width: 768px) {
  .results-container {
    gap: 1rem;
  }

  .video-card {
    padding: 1rem;
    border-radius: 12px;
  }

  .tab-bar {
    gap: 0.125rem;
  }

  .tab-button {
    padding: 0.5rem 0.625rem;
    font-size: 0.8125rem;
    gap: 0.25rem;
    min-height: 44px;
  }

  .tab-icon {
    width: 14px;
    height: 14px;
  }
}
</style>
