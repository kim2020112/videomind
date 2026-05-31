<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useDownloader } from './composables/useDownloader.js'
import NavBar from './components/NavBar.vue'
import HeroSection from './components/HeroSection.vue'
import FeaturesSection from './components/FeaturesSection.vue'
import FooterSection from './components/FooterSection.vue'
import AiSummary from './components/AiSummary.vue'
import HistoryPage from './components/HistoryPage.vue'
import VideoPlayerModal from './components/VideoPlayerModal.vue'
import { useSummary } from './composables/useSummary.js'
import { useChat } from './composables/useChat.js'
import { useQa } from './composables/useQa.js'
import { useAuth } from './composables/useAuth.js'
import { useTaskPoller } from './composables/useTaskPoller.js'

const { init: initAuth, isLoggedIn } = useAuth()
const { activeTasks, activeTaskCount, startPolling, stopPolling } = useTaskPoller()

onMounted(() => {
  initAuth()
  startPolling()
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
const currentView = ref('home') // 'home' | 'history'

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

function toggleHistory() {
  if (currentView.value === 'history') {
    currentView.value = 'home'
  } else {
    currentView.value = 'history'
  }
  window.scrollTo(0, 0)
}

async function handleSelectHistory(item) {
  url.value = item.url
  currentView.value = 'home'
  await handleParse()
  if (videoInfo.value && !error.value) {
    handleSummarize(false)
  }
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
  toggleExpand: toggleQaExpand,
  resetQa,
} = useQa()

const displayQaPairs = computed(() => {
  if (qaPairs.value.length > 0) return qaPairs.value
  return summaryQaPairs.value || []
})

async function handleSummarize(force = false) {
  if (!videoInfo.value) return
  try {
    await summarizeVideoStream(summarizeUrl.value, null, force, 'full')
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

const manualSubtitles = computed(() => subtitles.value.filter(s => !s.is_auto))
const autoSubtitles = computed(() => subtitles.value.filter(s => s.is_auto))

// 计算选中分P的总大小
const selectedPartsTotalSize = computed(() => {
  if (!videoInfo.value?.parts || selectedPartIndices.value.length === 0) return null
  const selectedSet = new Set(selectedPartIndices.value)
  let total = 0
  let hasSize = false
  for (const part of videoInfo.value.parts) {
    if (selectedSet.has(part.index) && part.filesize) {
      total += part.filesize
      hasSize = true
    }
  }
  return hasSize ? formatBytes(total) : null
})

function formatBytes(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB'
}

// 从格式标签中去掉单P大小（如 "，约 3.2 MB"），避免与动态总大小重复显示
function stripSizeFromLabel(label) {
  if (!label) return ''
  return label.replace(/[，,]\s*约?\s*[\d.]+\s*[KMGT]?B\s*$/i, '').trim()
}

const langNames = {
  'en': 'English', 'zh-Hans': '中文', 'zh': '中文', 'zh-CN': '中文',
  'ja': '日本語', 'ko': '한국어', 'fr': 'Français', 'de': 'Deutsch',
  'es': 'Español', 'pt': 'Português', 'ru': 'Русский', 'it': 'Italiano',
  'ar': 'العربية', 'th': 'ไทย', 'vi': 'Tiếng Việt', 'id': 'Bahasa Indonesia',
}

function subtitleDisplayName(sub) {
  // 翻译字幕：zh-Hans-en → "中文（从 English 翻译）"
  const parts = sub.lang.split('-')
  if (parts.length >= 2) {
    const target = parts[0]
    const source = parts.slice(1).join('-')
    const targetName = langNames[target] || target
    const sourceName = langNames[source] || source
    return `${targetName}（从 ${sourceName} 翻译）`
  }
  return sub.name || sub.lang
}

const translateLangs = [
  { code: 'zh-Hans', name: '中文' },
  { code: 'en', name: 'English' },
  { code: 'ja', name: '日本語' },
  { code: 'ko', name: '한국어' },
  { code: 'fr', name: 'Français' },
  { code: 'de', name: 'Deutsch' },
  { code: 'es', name: 'Español' },
]

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
  currentView.value = 'home'
  window.scrollTo(0, 0)
}

async function handleParse() {
  if (!url.value.trim()) return
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
    // 静默入库（fire-and-forget）
    fetch('/api/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url.value.trim() }),
    }).catch(() => {})
  } catch (e) {
    error.value = e.message || '解析失败，请检查链接是否有效'
  } finally {
    loading.value = false
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

function formatViewCount(count) {
  if (!count) return ''
  if (count >= 10000) return (count / 10000).toFixed(1).replace(/\.0$/, '') + '万'
  return count.toLocaleString()
}

function formatDuration(seconds) {
  if (!seconds) return ''
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m} 分钟`
}

function formatTime(timestamp) {
  if (!timestamp) return ''
  const d = new Date(timestamp)
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  const time = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  return isToday ? time : d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) + ' ' + time
}
</script>

<template>
  <div class="app-container">
    <NavBar :currentView="currentView" :activeTaskCount="activeTaskCount" @toggle-history="toggleHistory" @logout="handleLogout" @go-home="currentView = 'home'; $nextTick(() => window.scrollTo(0, 0))" />

    <!-- 学习历史页 -->
    <HistoryPage v-if="currentView === 'history'" :activeTasks="activeTasks" @select-item="handleSelectHistory" />

    <!-- 首页内容 -->
    <template v-if="currentView === 'home'">

    <HeroSection
      v-model:url="url"
      :loading="loading"
      :onParse="handleParse"
    />

    <!-- Results Section -->
    <section v-if="videoInfo || error" class="results-section">
      <div class="results-container">
        <!-- Error Message -->
        <div v-if="error" class="error-card">
          <svg class="error-icon" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
          </svg>
          <span>{{ error }}</span>
        </div>

        <!-- Video Info Card -->
        <div v-if="videoInfo" class="video-card">
          <div class="video-info">
            <div class="video-thumbnail-wrapper" :class="{ clickable: videoInfo.stream_url }" @click="openVideoModal" @keydown.enter="openVideoModal" tabindex="0" role="button">
              <img v-if="videoInfo.thumbnail" :src="videoInfo.thumbnail" :alt="videoInfo.title || '视频缩略图'" class="video-thumbnail" />
              <div v-if="videoInfo.stream_url" class="video-thumbnail-play">
                <svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
              </div>
              <span v-if="videoInfo.duration_string" class="video-thumbnail-duration">{{ currentSummarizePartInfo?.duration ? formatDuration(currentSummarizePartInfo.duration) : videoInfo.duration_string }}</span>
            </div>
            <div class="video-details">
              <h3 class="video-title">
                {{ videoInfo.title }}
                <span v-if="currentSummarizePartInfo && currentSummarizePartInfo.index > 1" class="part-badge">P{{ currentSummarizePartInfo.index }}</span>
              </h3>
              <div class="video-meta-row">
                <span class="video-meta-item">{{ videoInfo.extractor }}</span>
                <span v-if="videoInfo.uploader" class="video-meta-item">{{ videoInfo.uploader }}</span>
                <span v-if="videoInfo.view_count" class="video-meta-item">{{ formatViewCount(videoInfo.view_count) }} 次播放</span>
              </div>
              <a v-if="videoInfo.webpage_url" :href="videoInfo.webpage_url" target="_blank" rel="noopener" class="video-original-link">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
                查看原视频
              </a>
            </div>
          </div>

          <!-- Chapters -->
          <!-- Video Description -->
          <div v-if="videoInfo.description" class="video-description" :class="{ expanded: showFullDescription }">
            <p class="video-description-text">{{ videoInfo.description }}</p>
            <button
              v-if="videoInfo.description.length > 150"
              class="description-toggle"
              @click="showFullDescription = !showFullDescription"
            >
              {{ showFullDescription ? '收起' : '展开全部' }}
            </button>
          </div>

          <!-- Tab 栏 -->
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
          <!-- 分P选择器 -->
          <div v-if="videoInfo.parts && videoInfo.parts.length" class="parts-section">
            <div class="parts-header">
              <p class="parts-label">
                分P列表（共 {{ videoInfo.parts.length }} P）
                <span v-if="selectedPartIndices.length > 0" class="parts-total-size">
                  · 选中 {{ selectedPartIndices.length }} P
                </span>
              </p>
              <div class="parts-actions">
                <button @click="handleSelectAll" class="select-all-button">
                  {{ isAllPartsSelected ? '取消全选' : '全选' }}
                </button>
                <button
                  v-if="selectedPartIndices.length >= 1"
                  @click="handleDownloadSelected"
                  :disabled="progress && progress.status === 'downloading'"
                  class="download-selected-button"
                >下载选中({{ selectedPartIndices.length }})</button>
                <button
                  @click="handleDownloadAll"
                  :disabled="progress && progress.status === 'downloading'"
                  class="download-all-button"
                >合并下载全部</button>
              </div>
            </div>
            <div class="parts-list">
              <div
                v-for="part in videoInfo.parts"
                :key="part.index"
                class="part-row"
                :class="{ active: currentPart === part.index, selected: selectedPartIndices.includes(part.index) }"
              >
                <div
                  class="part-checkbox"
                  :class="{ checked: selectedPartIndices.includes(part.index) }"
                  @click="togglePartSelection(part.index)"
                >
                  <svg v-if="selectedPartIndices.includes(part.index)" viewBox="0 0 12 10" fill="none">
                    <path d="M1 5l3 3.5L11 1" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                </div>
                <div class="part-info">
                  <span class="part-index">P{{ part.index }}</span>
                  <span class="part-title">{{ part.title }}</span>
                  <span v-if="part.filesize_str" class="part-filesize">{{ part.filesize_str }}</span>
                  <span v-if="part.duration" class="part-duration">{{ formatDuration(part.duration) }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Format Selection -->
          <div v-if="displayFormats.length" class="format-section">
            <p class="format-label">选择清晰度</p>
            <div class="format-grid">
              <button
                v-for="f in displayFormats"
                :key="f.format_id"
                @click="selectedFormat = f.format_id"
                class="format-button"
                :class="{
                  active: selectedFormat === f.format_id,
                  'format-best': f.is_best,
                  'format-audio': f.is_audio_only,
                }"
              >
                <span v-if="f.is_best" class="format-badge-best">
                  <svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 .25a.75.75 0 01.673.418l1.882 3.815 4.21.612a.75.75 0 01.416 1.279l-3.046 2.97.719 4.192a.75.75 0 01-1.088.791L8 12.347l-3.766 1.98a.75.75 0 01-1.088-.79l.72-4.194L.818 6.374a.75.75 0 01.416-1.28l4.21-.611L7.327.668A.75.75 0 018 .25z"/></svg>
                  推荐
                </span>
                <span class="format-name">{{ f.is_audio_only ? (f.label || f.ext.toUpperCase()) : stripSizeFromLabel(f.label) || (f.height ? f.height + 'p' : f.ext.toUpperCase()) }}</span>
                <span class="format-sub">
                  <span v-if="f.is_audio_only" class="format-tag-audio">仅音频</span>
                  <template v-else>{{ f.ext.toUpperCase() }}</template>
                  <template v-if="f.adjusted_filesize_str"> · {{ f.adjusted_filesize_str }}</template>
                  <template v-else-if="f.filesize_str"> · {{ f.filesize_str }}</template>
                </span>
              </button>
            </div>
          </div>

          <!-- Subtitle Section (collapsible) -->
          <div v-if="subtitles.length" class="subtitle-section">
            <button
              type="button"
              class="subtitle-collapse-toggle"
              :aria-expanded="showSubtitles"
              @click="showSubtitles = !showSubtitles"
            >
              <svg
                class="subtitle-toggle-chevron"
                :class="{ rotated: showSubtitles }"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd"/>
              </svg>
              <span class="subtitle-toggle-label">
                字幕文件（{{ subtitles.length }}）
              </span>
              <span class="subtitle-toggle-desc">下载 .srt/.vtt 文本文件（不嵌入视频）</span>
            </button>
            <div v-show="showSubtitles" class="subtitle-expanded">
              <div class="subtitle-disclaimer">
                <svg viewBox="0 0 20 20" fill="currentColor" class="subtitle-disclaimer-icon">
                  <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/>
                </svg>
                <span>字幕将以独立文件下载，不会嵌入到视频中。如需内嵌字幕，请使用视频编辑软件手动合成。</span>
              </div>
              <div class="subtitle-translate-bar">
                <span class="subtitle-translate-hint">翻译目标语言：</span>
                <select v-model="translateTargetLang" class="subtitle-lang-select">
                  <option v-for="lang in translateLangs" :key="lang.code" :value="lang.code">
                    {{ lang.name }}
                  </option>
                </select>
              </div>
              <div v-if="manualSubtitles.length" class="subtitle-group">
                <p class="subtitle-group-label">手动字幕</p>
                <div class="subtitle-list">
                  <div v-for="sub in manualSubtitles" :key="sub.lang" class="subtitle-item">
                    <span class="subtitle-name">{{ subtitleDisplayName(sub) }}（{{ sub.ext }}）</span>
                    <div class="subtitle-actions">
                      <button @click="handleDownloadSubtitle(sub)" class="subtitle-btn subtitle-download-btn">下载</button>
                      <button @click="handleTranslateSubtitle(sub)" class="subtitle-btn subtitle-translate-btn">翻译</button>
                    </div>
                  </div>
                </div>
              </div>
              <div v-if="autoSubtitles.length" class="subtitle-group">
                <p class="subtitle-group-label">自动生成字幕</p>
                <div class="subtitle-list">
                  <div v-for="sub in autoSubtitles" :key="sub.lang" class="subtitle-item">
                    <span class="subtitle-name">{{ subtitleDisplayName(sub) }}（{{ sub.ext }}）</span>
                    <div class="subtitle-actions">
                      <button @click="handleDownloadSubtitle(sub)" class="subtitle-btn subtitle-download-btn">下载</button>
                      <button @click="handleTranslateSubtitle(sub)" class="subtitle-btn subtitle-translate-btn">翻译</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Download Button (inline with format detail) -->
          <div v-if="selectedFormatDetail" class="format-detail">
            <span class="format-detail-item">格式：{{ selectedFormatDetail.ext.toUpperCase() }}</span>
            <span v-if="selectedFormatDetail.vcodec && selectedFormatDetail.vcodec !== 'none'" class="format-detail-item">编码：{{ selectedFormatDetail.vcodec }}</span>
            <span v-if="selectedFormatDetail.fps" class="format-detail-item">{{ selectedFormatDetail.fps }}fps</span>
            <span v-if="selectedFormatDetail.tbr" class="format-detail-item">{{ selectedFormatDetail.tbr }}kbps</span>
            <button
              @click="handleDownload"
              :disabled="progress && progress.status === 'downloading'"
              class="download-btn-inline"
            >
              <svg class="download-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              {{ progress && progress.status === 'downloading' ? '下载中...' : '下载' }}
            </button>
          </div>

          <!-- Download Progress -->
          <div v-if="progress" class="progress-card" :class="'progress-' + progress.status">
            <div class="progress-header">
              <span class="progress-label">
                <svg v-if="progress.status === 'completed'" class="progress-status-icon progress-status-success" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>
                <svg v-else-if="progress.status === 'failed'" class="progress-status-icon progress-status-error" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/></svg>
                {{ progress.status === 'completed' ? '下载完成' : progress.status === 'failed' ? '下载失败' : '下载中' }}
              </span>
              <span class="progress-percent">{{ progress.percent }}%</span>
            </div>
            <div class="progress-bar-container">
              <div class="progress-bar" :class="{ 'progress-bar-shimmer': progress.status === 'downloading' }" :style="{ width: progress.percent + '%' }"></div>
            </div>
            <div v-if="progress.speed" class="progress-info">
              {{ progress.speed }} · 剩余约 {{ progress.eta }} 秒
            </div>
            <div v-if="progress.error" class="progress-error">{{ progress.error }}</div>
          </div>
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
              :backgroundTask="backgroundTask"
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

        <!-- Download History -->
        <div v-if="downloadHistory.length" class="history-card">
          <p class="history-label">下载记录</p>
          <div class="history-list">
            <div v-for="item in downloadHistory" :key="item.task_id" class="history-item">
              <svg v-if="item.status === 'completed'" class="history-status-icon history-status-success" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>
              <svg v-else class="history-status-icon history-status-error" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/></svg>
              <div class="history-item-content">
                <span class="history-title">{{ item.title }}</span>
                <span v-if="item.time" class="history-time">{{ formatTime(item.time) }}</span>
              </div>
              <button
                v-if="item.status === 'completed'"
                @click="handleDownloadFile(item.task_id)"
                class="save-button"
              >
                <svg viewBox="0 0 20 20" fill="currentColor" class="save-icon"><path d="M10.75 2.75a.75.75 0 00-1.5 0v8.614L6.295 8.235a.75.75 0 10-1.09 1.03l4.25 4.5a.75.75 0 001.09 0l4.25-4.5a.75.75 0 00-1.09-1.03l-2.955 3.129V2.75z"/><path d="M3.5 12.75a.75.75 0 00-1.5 0v2.5A2.75 2.75 0 004.75 18h10.5A2.75 2.75 0 0018 15.25v-2.5a.75.75 0 00-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5z"/></svg>
                保存
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>

    </template>

    <FeaturesSection />
    <FooterSection />
    <VideoPlayerModal
      ref="videoPlayerRef"
      :visible="showVideoModal"
      :streamUrl="videoStreamUrl"
      :videoTitle="videoInfo?.title || ''"
      :videoUrl="videoInfo?.webpage_url || ''"
      @close="showVideoModal = false"
      @seek="onVideoSeek"
    />
  </div>
</template>

<style scoped>
.app-container {
  min-height: 100vh;
  background: var(--bg-primary);
}

.results-section {
  padding: 3rem 2rem;
  background: var(--bg-primary);
}

.results-container {
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
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

.video-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 2rem;
  backdrop-filter: blur(12px);
}

.video-info {
  display: flex;
  gap: 1.25rem;
  margin-bottom: 1.25rem;
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
.tab-bar::-webkit-scrollbar { display: none; }

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

.tab-button:hover { color: var(--text-secondary); background: rgba(255, 255, 255, 0.05); }
.tab-button.active { background: rgba(59, 130, 246, 0.15); color: #93C5FD; }
.tab-icon { width: 16px; height: 16px; }

.video-thumbnail-wrapper {
  position: relative;
  width: 220px;
  flex-shrink: 0;
  border-radius: var(--radius);
  overflow: hidden;
}
.video-thumbnail-wrapper.clickable {
  cursor: pointer;
}

.video-thumbnail {
  width: 100%;
  height: 124px;
  object-fit: cover;
  display: block;
}

.video-thumbnail-play {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 44px;
  height: 44px;
  background: rgba(0, 0, 0, 0.5);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  opacity: 0;
  transition: opacity 0.2s;
}

.video-thumbnail-wrapper:hover .video-thumbnail-play {
  opacity: 1;
}

.video-thumbnail-play svg {
  width: 22px;
  height: 22px;
  margin-left: 2px;
}

.video-thumbnail-duration {
  position: absolute;
  bottom: 6px;
  right: 6px;
  padding: 0.125rem 0.4375rem;
  background: rgba(0, 0, 0, 0.75);
  border-radius: 4px;
  font-size: 0.6875rem;
  font-weight: 600;
  color: white;
  font-variant-numeric: tabular-nums;
}

.video-details {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.video-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 0.625rem;
  line-height: 1.4;
}

.part-badge {
  display: inline-block;
  vertical-align: middle;
  margin-left: 0.5rem;
  padding: 0.125rem 0.5rem;
  font-size: 0.75rem;
  font-weight: 700;
  color: #93C5FD;
  background: rgba(59, 130, 246, 0.15);
  border: 1px solid rgba(59, 130, 246, 0.25);
  border-radius: 6px;
}

.video-meta-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.375rem;
  margin-bottom: 0.625rem;
}

.video-meta-item {
  font-size: 0.8125rem;
  color: var(--text-secondary);
  padding: 0.125rem 0.5rem;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
}

.video-original-link {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  color: var(--text-muted);
  transition: color 0.2s;
  margin-top: auto;
}

.video-original-link:hover {
  color: var(--accent-blue);
}

.video-original-link svg {
  width: 14px;
  height: 14px;
}

.video-description {
  margin-bottom: 1rem;
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid var(--border);
  border-radius: 10px;
  position: relative;
}
.video-description-text {
  font-size: 0.8125rem;
  line-height: 1.6;
  color: var(--text-muted);
  margin: 0;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.video-description.expanded .video-description-text {
  display: block;
  -webkit-line-clamp: unset;
}
.description-toggle {
  display: inline-block;
  margin-top: 0.375rem;
  padding: 0;
  background: none;
  border: none;
  color: var(--accent-blue);
  font-size: 0.75rem;
  cursor: pointer;
}
.description-toggle:hover {
  color: var(--accent-cyan);
}

.format-section {
  margin-bottom: 1.5rem;
}

.format-label {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 0.75rem;
}

.format-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.625rem;
}

.format-button {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 0.25rem;
  padding: 0.75rem 1rem;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
  line-height: 1.4;
}

.format-button:hover {
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

.format-button.active {
  background: rgba(59, 130, 246, 0.15);
  border-color: var(--accent-blue);
  color: #93C5FD;
}

.format-button.format-best {
  background: rgba(59, 130, 246, 0.08);
  border-color: rgba(59, 130, 246, 0.25);
}

.format-button.format-best.active {
  background: rgba(59, 130, 246, 0.2);
  border-color: var(--accent-blue);
}

.format-button.format-audio {
  background: rgba(16, 185, 129, 0.08);
  border-color: rgba(16, 185, 129, 0.15);
}

.format-button.format-audio:hover {
  border-color: rgba(16, 185, 129, 0.3);
}

.format-button.format-audio.active {
  background: rgba(16, 185, 129, 0.2);
  border-color: var(--success);
  color: #6EE7B7;
}

.format-badge-best {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.625rem;
  font-weight: 700;
  color: #FCD34D;
}

.format-badge-best svg {
  width: 10px;
  height: 10px;
}

.format-name {
  font-weight: 600;
  font-size: 0.9375rem;
}

.format-sub {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.format-tag-audio {
  color: #6EE7B7;
}

.format-detail {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border);
}
.download-btn-inline {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.4375rem 1rem;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.2) 0%, rgba(6, 182, 212, 0.15) 100%);
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 8px;
  color: #93C5FD;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.download-btn-inline:hover:not(:disabled) {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.3) 0%, rgba(6, 182, 212, 0.25) 100%);
  border-color: rgba(59, 130, 246, 0.5);
  transform: translateY(-1px);
}
.download-btn-inline:disabled { opacity: 0.4; cursor: not-allowed; }

.format-detail-item {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.subtitle-section {
  margin-bottom: 1.5rem;
}

.subtitle-collapse-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 0.875rem;
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text-secondary);
  font-size: 0.8125rem;
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
}

.subtitle-collapse-toggle:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

.subtitle-toggle-chevron {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  transition: transform 0.2s;
  color: var(--text-muted);
}

.subtitle-toggle-chevron.rotated {
  transform: rotate(90deg);
}

.subtitle-toggle-label {
  font-weight: 600;
  white-space: nowrap;
}

.subtitle-toggle-desc {
  color: var(--text-muted);
  font-size: 0.75rem;
  margin-left: auto;
}

.subtitle-disclaimer {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.625rem 0.75rem;
  margin-bottom: 0.75rem;
  background: rgba(251, 191, 36, 0.08);
  border: 1px solid rgba(251, 191, 36, 0.15);
  border-radius: 8px;
  font-size: 0.75rem;
  color: var(--text-muted);
  line-height: 1.5;
}

.subtitle-disclaimer-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  color: #FCD34D;
  margin-top: 1px;
}

.subtitle-expanded {
  margin-top: 0.5rem;
}

.subtitle-translate-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.subtitle-translate-hint {
  font-size: 0.8125rem;
  color: var(--text-primary);
  white-space: nowrap;
}

.subtitle-lang-select {
  padding: 0.375rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 0.8125rem;
  color: var(--text-primary);
  background: var(--bg-secondary);
  cursor: pointer;
  outline: none;
  appearance: none;
  -webkit-appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%2394A3B8' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.625rem center;
  padding-right: 2rem;
}

.subtitle-lang-select option {
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.subtitle-lang-select:focus {
  border-color: var(--accent-blue);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}

.subtitle-group {
  margin-bottom: 0.75rem;
}

.subtitle-group-label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 0.375rem;
}

.subtitle-list {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  max-height: 180px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0.375rem;
}

.subtitle-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.625rem;
  border-radius: 7px;
  transition: background 0.15s;
  gap: 0.5rem;
}

.subtitle-item:hover {
  background: var(--bg-card-hover);
}

.subtitle-name {
  font-size: 0.8125rem;
  color: var(--text-primary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subtitle-actions {
  display: flex;
  gap: 0.375rem;
  flex-shrink: 0;
}

.subtitle-btn {
  padding: 0.25rem 0.625rem;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.subtitle-download-btn {
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.2);
  color: #93C5FD;
}

.subtitle-download-btn:hover {
  background: rgba(59, 130, 246, 0.2);
}

.subtitle-translate-btn {
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.2);
  color: #6EE7B7;
}

.subtitle-translate-btn:hover {
  background: rgba(16, 185, 129, 0.2);
}


.download-icon {
  width: 20px;
  height: 20px;
}

.progress-card {
  margin-top: 1.5rem;
  padding: 1.25rem;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  transition: border-color 0.3s;
}

.progress-card.progress-completed {
  border-color: rgba(16, 185, 129, 0.3);
}

.progress-card.progress-failed {
  border-color: rgba(239, 68, 68, 0.3);
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.progress-label {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary);
}

.progress-status-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.progress-status-success {
  color: var(--success);
}

.progress-status-error {
  color: var(--error);
}

.progress-percent {
  font-size: 0.875rem;
  font-weight: 700;
  color: var(--accent-cyan);
  font-variant-numeric: tabular-nums;
}

.progress-bar-container {
  width: 100%;
  height: 6px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 3px;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-blue) 0%, var(--accent-cyan) 100%);
  border-radius: 3px;
  transition: width 0.3s;
  position: relative;
}

.progress-bar-shimmer {
  background: linear-gradient(
    90deg,
    var(--accent-blue) 0%,
    var(--accent-cyan) 40%,
    #67e8f9 50%,
    var(--accent-cyan) 60%,
    var(--accent-blue) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
}

.progress-card.progress-completed .progress-bar {
  background: linear-gradient(90deg, var(--success) 0%, #34d399 100%);
}

.progress-card.progress-failed .progress-bar {
  background: linear-gradient(90deg, var(--error) 0%, #f87171 100%);
}

.progress-info {
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.progress-error {
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: #FCA5A5;
}

.history-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 1.5rem;
  backdrop-filter: blur(12px);
}

.history-label {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 1rem;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border);
  border-radius: 10px;
}

.history-status-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.history-status-success {
  color: var(--success);
}

.history-status-error {
  color: var(--error);
}

.history-item-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.history-title {
  font-size: 0.8125rem;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-time {
  font-size: 0.6875rem;
  color: var(--text-muted);
}

.save-button {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.4375rem 1rem;
  background: transparent;
  border: 1px solid var(--accent-blue);
  border-radius: 8px;
  color: var(--accent-blue);
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
  flex-shrink: 0;
}

.save-button:hover {
  background: rgba(59, 130, 246, 0.15);
}

.save-icon {
  width: 16px;
  height: 16px;
}

.parts-section {
  margin-bottom: 1.5rem;
}

.parts-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.parts-label {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.parts-total-size {
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--accent-cyan);
}

.parts-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.select-all-button {
  padding: 0.375rem 0.75rem;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.select-all-button:hover {
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

.download-selected-button {
  padding: 0.375rem 0.875rem;
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: 8px;
  color: #93C5FD;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.download-selected-button:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.2);
}

.download-selected-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.parts-list {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0.375rem;
}

.part-row {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  border-radius: 8px;
  transition: background 0.15s;
  min-height: 44px;
}

.part-row:hover {
  background: rgba(255,255,255,0.05);
}

.part-row.active {
  background: rgba(59,130,246,0.1);
}

.part-row.selected {
  background: rgba(59,130,246,0.1);
}

.part-checkbox {
  width: 20px;
  height: 20px;
  border: 2px solid rgba(255, 255, 255, 0.2);
  border-radius: 5px;
  flex-shrink: 0;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
  margin-left: 0.375rem;
}

.part-checkbox:hover {
  border-color: var(--accent-blue);
}

.part-checkbox.checked {
  background: var(--accent-blue);
  border-color: var(--accent-blue);
}

.part-checkbox svg {
  width: 12px;
  height: 10px;
}

.part-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1;
  padding: 0.5rem 0.375rem 0.5rem 0;
  min-width: 0;
}

.part-index {
  font-weight: 700;
  color: var(--accent-blue);
  min-width: 2rem;
  flex-shrink: 0;
  font-size: 0.8125rem;
}

.part-title {
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.8125rem;
  transition: color 0.15s;
  flex: 1;
  min-width: 0;
}

.part-filesize {
  font-size: 0.75rem;
  color: var(--text-muted);
  flex-shrink: 0;
}

.part-duration {
  font-size: 0.75rem;
  color: var(--text-muted);
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
  margin-left: auto;
  padding-left: 0.5rem;
}

.download-all-button {
  padding: 0.375rem 0.875rem;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.2);
  border-radius: 8px;
  color: #6EE7B7;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.download-all-button:hover:not(:disabled) {
  background: rgba(16, 185, 129, 0.2);
  border-color: rgba(16, 185, 129, 0.4);
}

.download-all-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 768px) {
  .results-section { padding: 1.5rem 0.75rem; }
  .results-container { gap: 1rem; }
  .video-card { padding: 1rem; border-radius: 12px; }
  .video-info { flex-direction: column; gap: 0.75rem; }
  .video-thumbnail-wrapper { width: 100%; }
  .video-thumbnail { width: 100%; height: auto; }
  .video-thumbnail-play { opacity: 1; }
  .video-title { font-size: 0.9375rem; }
  .video-meta-row { flex-wrap: wrap; gap: 0.375rem; }
  .video-meta-item { font-size: 0.6875rem; }
  .video-original-link { font-size: 0.75rem; }

  /* 下载区域 */
  .format-grid { grid-template-columns: 1fr; }
  .format-button { padding: 0.625rem 0.75rem; }
  .parts-section { font-size: 0.8125rem; }
  .part-row { padding: 0.5rem; }
  .part-title { font-size: 0.8125rem; }

  /* Tab 栏 */
  .tab-bar { gap: 0.125rem; }
  .tab-button { padding: 0.5rem 0.625rem; font-size: 0.8125rem; gap: 0.25rem; }
  .tab-icon { width: 14px; height: 14px; }

  /* 历史 */
  .history-item { flex-wrap: wrap; }
  .history-item-content { width: calc(100% - 42px); }
  .save-button { width: 100%; margin-top: 0.25rem; }

  /* 描述 */
  .description-text { font-size: 0.8125rem; }
}

</style>