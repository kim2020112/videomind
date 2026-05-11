<script setup>
import { ref, computed } from 'vue'
import { useDownloader } from './composables/useDownloader.js'
import NavBar from './components/NavBar.vue'
import HeroSection from './components/HeroSection.vue'
import FeaturesSection from './components/FeaturesSection.vue'

const {
  videoInfo,
  formats,
  selectedFormat,
  progress,
  downloadHistory,
  parseVideo,
  startDownload,
  startDownloadAll,
  startDownloadSelected,
  downloadFile,
  reset,
} = useDownloader()

const url = ref('')
const error = ref('')
const loading = ref(false)
const selectedPartIndices = ref([])

const displayFormats = computed(() => formats.value)

const currentPart = computed(() => {
  const m = url.value.match(/[?&]p=(\d+)/)
  return m ? parseInt(m[1]) : 1
})

const isAllPartsSelected = computed(() =>
  videoInfo.value?.parts?.length > 0 &&
  selectedPartIndices.value.length === videoInfo.value.parts.length
)

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

async function handleParse() {
  if (!url.value.trim()) return
  error.value = ''
  loading.value = true
  selectedPartIndices.value = []
  reset()
  try {
    await parseVideo(url.value.trim())
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
  startDownload(videoInfo.value.webpage_url)
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
    <NavBar />
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
            <img v-if="videoInfo.thumbnail" :src="videoInfo.thumbnail" class="video-thumbnail" />
            <div class="video-details">
              <h3 class="video-title">{{ videoInfo.title }}</h3>
              <p class="video-meta">{{ videoInfo.extractor }} · {{ videoInfo.duration_string }}</p>
            </div>
          </div>

          <!-- 分P选择器 -->
          <div v-if="videoInfo.parts && videoInfo.parts.length" class="parts-section">
            <div class="parts-header">
              <p class="parts-label">分P列表（共 {{ videoInfo.parts.length }} P）</p>
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
                <button class="part-info" @click="handlePartSelect(part)">
                  <span class="part-index">P{{ part.index }}</span>
                  <span class="part-title">{{ part.title }}</span>
                </button>
              </div>
            </div>
          </div>

          <!-- Format Selection -->
          <div v-if="displayFormats.length" class="format-section">
            <p class="format-label">选择清晰度和格式</p>
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
                <span v-if="f.is_best" class="format-badge">⭐ 推荐</span>
                {{ f.label || (f.height ? f.height + 'p' : f.ext.toUpperCase()) }}
              </button>
            </div>
          </div>

          <!-- Download Button -->
          <button
            v-if="displayFormats.length"
            @click="handleDownload"
            :disabled="progress && progress.status === 'downloading'"
            class="download-button"
          >
            <svg class="download-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            {{ progress && progress.status === 'downloading' ? '下载中...' : '开始下载' }}
          </button>

          <!-- Download Progress -->
          <div v-if="progress" class="progress-card">
            <div class="progress-header">
              <span class="progress-label">
                {{ progress.status === 'completed' ? '下载完成' : progress.status === 'failed' ? '下载失败' : '下载中' }}
              </span>
              <span class="progress-percent">{{ progress.percent }}%</span>
            </div>
            <div class="progress-bar-container">
              <div class="progress-bar" :style="{ width: progress.percent + '%' }"></div>
            </div>
            <div v-if="progress.speed" class="progress-info">
              {{ progress.speed }} · 剩余约 {{ progress.eta }} 秒
            </div>
            <div v-if="progress.error" class="progress-error">{{ progress.error }}</div>
          </div>
        </div>

        <!-- Download History -->
        <div v-if="downloadHistory.length" class="history-card">
          <p class="history-label">下载记录</p>
          <div class="history-list">
            <div v-for="item in downloadHistory" :key="item.task_id" class="history-item">
              <span class="history-title">{{ item.title }}</span>
              <button
                v-if="item.status === 'completed'"
                @click="handleDownloadFile(item.task_id)"
                class="save-button"
              >
                保存
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <FeaturesSection />
  </div>
</template>

<style scoped>
.app-container {
  min-height: 100vh;
  background: white;
}

.results-section {
  padding: 3rem 2rem;
  background: white;
}

.results-container {
  max-width: 800px;
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
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 12px;
  color: #dc2626;
  font-size: 0.9375rem;
}

.error-icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
}

.video-card {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  padding: 2rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.video-info {
  display: flex;
  gap: 1.25rem;
  margin-bottom: 1.5rem;
}

.video-thumbnail {
  width: 200px;
  height: 112px;
  object-fit: cover;
  border-radius: 12px;
  flex-shrink: 0;
}

.video-details {
  flex: 1;
  min-width: 0;
}

.video-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 0.5rem;
  line-height: 1.4;
}

.video-meta {
  font-size: 0.875rem;
  color: #6b7280;
}

.format-section {
  margin-bottom: 1.5rem;
}

.format-label {
  font-size: 0.9375rem;
  font-weight: 600;
  color: #374151;
  margin-bottom: 0.75rem;
}

.format-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.format-button {
  padding: 0.625rem 1.25rem;
  background: #f3f4f6;
  border: 2px solid transparent;
  border-radius: 10px;
  font-size: 0.875rem;
  font-weight: 500;
  color: #4b5563;
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
  line-height: 1.4;
  position: relative;
}

.format-button:hover {
  background: #e5e7eb;
}

.format-button.active {
  background: #dbeafe;
  border-color: #3b82f6;
  color: #2563eb;
}

.format-button.format-best {
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
  border-color: #93c5fd;
  color: #1d4ed8;
  font-weight: 600;
}

.format-button.format-best.active {
  background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
  border-color: #3b82f6;
}

.format-button.format-audio {
  background: #f0fdf4;
  color: #166534;
}

.format-button.format-audio.active {
  background: #dcfce7;
  border-color: #22c55e;
  color: #15803d;
}

.format-badge {
  display: block;
  font-size: 0.7rem;
  font-weight: 700;
  color: #f59e0b;
  margin-bottom: 2px;
}

.download-button {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 1rem;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: white;
  border: none;
  border-radius: 12px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
}

.download-button:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(59, 130, 246, 0.4);
}

.download-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.download-icon {
  width: 20px;
  height: 20px;
}

.progress-card {
  margin-top: 1.5rem;
  padding: 1.25rem;
  background: #f9fafb;
  border-radius: 12px;
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.progress-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #374151;
}

.progress-percent {
  font-size: 0.875rem;
  font-weight: 700;
  color: #3b82f6;
}

.progress-bar-container {
  width: 100%;
  height: 8px;
  background: #e5e7eb;
  border-radius: 4px;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6 0%, #2563eb 100%);
  border-radius: 4px;
  transition: width 0.3s;
}

.progress-info {
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: #6b7280;
}

.progress-error {
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: #dc2626;
}

.history-card {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  padding: 1.5rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.history-label {
  font-size: 0.9375rem;
  font-weight: 600;
  color: #374151;
  margin-bottom: 1rem;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.history-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.875rem 1rem;
  background: #f9fafb;
  border-radius: 10px;
}

.history-title {
  flex: 1;
  font-size: 0.875rem;
  color: #374151;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-right: 1rem;
}

.save-button {
  padding: 0.5rem 1.25rem;
  background: transparent;
  border: 1px solid #3b82f6;
  border-radius: 8px;
  color: #3b82f6;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.save-button:hover {
  background: #3b82f6;
  color: white;
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
  color: #374151;
  margin: 0;
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
  border: 1px solid #d1d5db;
  border-radius: 8px;
  color: #6b7280;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.select-all-button:hover {
  background: #f3f4f6;
  border-color: #9ca3af;
}

.download-selected-button {
  padding: 0.375rem 0.875rem;
  background: #eff6ff;
  border: 1px solid #93c5fd;
  border-radius: 8px;
  color: #2563eb;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.download-selected-button:hover:not(:disabled) {
  background: #dbeafe;
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
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 0.375rem;
}

.part-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  border-radius: 7px;
  transition: background 0.15s;
}

.part-row:hover {
  background: #f9fafb;
}

.part-row.selected {
  background: #eff6ff;
}

.part-checkbox {
  width: 18px;
  height: 18px;
  border: 2px solid #d1d5db;
  border-radius: 4px;
  flex-shrink: 0;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
  margin-left: 0.375rem;
}

.part-checkbox:hover {
  border-color: #3b82f6;
}

.part-checkbox.checked {
  background: #3b82f6;
  border-color: #3b82f6;
}

.part-checkbox svg {
  width: 12px;
  height: 10px;
}

.part-info {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  flex: 1;
  padding: 0.5rem 0.5rem 0.5rem 0;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  min-width: 0;
}

.part-info:hover .part-title {
  color: #2563eb;
}

.part-index {
  font-weight: 700;
  color: #3b82f6;
  min-width: 2.5rem;
  flex-shrink: 0;
  font-size: 0.875rem;
}

.part-title {
  color: #374151;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.875rem;
  transition: color 0.15s;
}

.download-all-button {
  padding: 0.375rem 0.875rem;
  background: #f0fdf4;
  border: 1px solid #86efac;
  border-radius: 8px;
  color: #15803d;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.download-all-button:hover:not(:disabled) {
  background: #dcfce7;
  border-color: #4ade80;
}

.download-all-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 768px) {
  .results-section { padding: 2rem 1rem; }
  .video-card { padding: 1.5rem; }
  .video-info { flex-direction: column; }
  .video-thumbnail { width: 100%; height: auto; }
  .history-item { flex-direction: column; align-items: flex-start; gap: 0.75rem; }
  .history-title { margin-right: 0; }
  .save-button { width: 100%; }
}
</style>