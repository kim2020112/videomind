<script setup>
import { computed } from 'vue'
import {
  formatDuration,
  stripSizeFromLabel,
  subtitleDisplayName,
  translateLangs,
} from '../utils/resultFormatters.js'

const props = defineProps({
  videoInfo: { type: Object, default: null },
  formats: { type: Array, default: () => [] },
  selectedFormat: { type: String, default: '' },
  selectedFormatDetail: { type: Object, default: null },
  selectedPartIndices: { type: Array, default: () => [] },
  currentPart: { type: Number, default: 1 },
  isAllPartsSelected: { type: Boolean, default: false },
  subtitles: { type: Array, default: () => [] },
  showSubtitles: { type: Boolean, default: false },
  translateTargetLang: { type: String, default: 'zh-Hans' },
  progress: { type: Object, default: null },
  variant: { type: String, default: 'mobile' },
})

const emit = defineEmits([
  'select-format',
  'toggle-part',
  'select-all-parts',
  'download',
  'download-selected',
  'download-all',
  'download-subtitle',
  'translate-subtitle',
  'update:showSubtitles',
  'update:translateTargetLang',
])

const manualSubtitles = computed(() => props.subtitles.filter((s) => !s.is_auto))
const autoSubtitles = computed(() => props.subtitles.filter((s) => s.is_auto))
const isSidebar = computed(() => props.variant === 'sidebar')
</script>

<template>
  <component
    :is="isSidebar ? 'details' : 'div'"
    class="download-tools"
    :class="{ 'download-tools--sidebar': isSidebar }"
  >
    <summary v-if="isSidebar" class="sidebar-download-summary">
      <span>视频下载</span>
      <span v-if="selectedPartIndices.length > 0" class="sidebar-download-meta">{{ selectedPartIndices.length }} P</span>
    </summary>

    <div class="download-tools-content">
      <div v-if="videoInfo?.parts && videoInfo.parts.length" class="parts-section">
        <div class="parts-header">
          <p class="parts-label">
            分P列表（共 {{ videoInfo.parts.length }} P）
            <span v-if="selectedPartIndices.length > 0" class="parts-total-size">
              · 选中 {{ selectedPartIndices.length }} P
            </span>
          </p>
          <div class="parts-actions">
            <button type="button" @click="emit('select-all-parts')" class="select-all-button">
              {{ isAllPartsSelected ? '取消全选' : '全选' }}
            </button>
            <button
              v-if="selectedPartIndices.length >= 1"
              type="button"
              @click="emit('download-selected')"
              :disabled="progress && progress.status === 'downloading'"
              class="download-selected-button"
            >
              下载选中({{ selectedPartIndices.length }})
            </button>
            <button
              type="button"
              @click="emit('download-all')"
              :disabled="progress && progress.status === 'downloading'"
              class="download-all-button"
            >
              {{ isSidebar ? '全部' : '合并下载全部' }}
            </button>
          </div>
        </div>

        <div class="parts-list" :class="{ 'parts-list--sidebar': isSidebar }">
          <div
            v-for="part in videoInfo.parts"
            :key="part.index"
            class="part-row"
            :class="{ active: currentPart === part.index, selected: selectedPartIndices.includes(part.index) }"
          >
            <button
              type="button"
              class="part-checkbox"
              :class="{ checked: selectedPartIndices.includes(part.index) }"
              :aria-label="`${selectedPartIndices.includes(part.index) ? '取消选择' : '选择'} P${part.index}`"
              @click="emit('toggle-part', part.index)"
            >
              <svg v-if="selectedPartIndices.includes(part.index)" viewBox="0 0 12 10" fill="none">
                <path d="M1 5l3 3.5L11 1" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </button>
            <div class="part-info">
              <span class="part-index">P{{ part.index }}</span>
              <span class="part-title">{{ part.title }}</span>
              <span v-if="!isSidebar && part.filesize_str" class="part-filesize">{{ part.filesize_str }}</span>
              <span v-if="part.duration" class="part-duration">{{ formatDuration(part.duration) }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="formats.length" class="format-section">
        <p class="format-label">选择清晰度</p>
        <div class="format-grid" :class="{ 'format-grid--sidebar': isSidebar }">
          <button
            v-for="f in formats"
            :key="f.format_id"
            type="button"
            @click="emit('select-format', f.format_id)"
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

      <div v-if="subtitles.length" class="subtitle-section">
        <button
          type="button"
          class="subtitle-collapse-toggle"
          :aria-expanded="showSubtitles"
          @click="emit('update:showSubtitles', !showSubtitles)"
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
          <span v-if="!isSidebar" class="subtitle-toggle-desc">下载 .srt/.vtt 文本文件（不嵌入视频）</span>
        </button>

        <div v-show="showSubtitles" class="subtitle-expanded">
          <div v-if="!isSidebar" class="subtitle-disclaimer">
            <svg viewBox="0 0 20 20" fill="currentColor" class="subtitle-disclaimer-icon">
              <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/>
            </svg>
            <span>字幕将以独立文件下载，不会嵌入到视频中。如需内嵌字幕，请使用视频编辑软件手动合成。</span>
          </div>

          <div class="subtitle-translate-bar">
            <span class="subtitle-translate-hint">{{ isSidebar ? '翻译：' : '翻译目标语言：' }}</span>
            <select
              :value="translateTargetLang"
              class="subtitle-lang-select"
              @change="emit('update:translateTargetLang', $event.target.value)"
            >
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
                  <button type="button" @click="emit('download-subtitle', sub)" class="subtitle-btn subtitle-download-btn">下载</button>
                  <button type="button" @click="emit('translate-subtitle', sub)" class="subtitle-btn subtitle-translate-btn">翻译</button>
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
                  <button type="button" @click="emit('download-subtitle', sub)" class="subtitle-btn subtitle-download-btn">下载</button>
                  <button type="button" @click="emit('translate-subtitle', sub)" class="subtitle-btn subtitle-translate-btn">翻译</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="selectedFormatDetail" class="format-detail" :class="{ 'format-detail--sidebar': isSidebar }">
        <span class="format-detail-item">格式：{{ selectedFormatDetail.ext.toUpperCase() }}</span>
        <span v-if="selectedFormatDetail.vcodec && selectedFormatDetail.vcodec !== 'none'" class="format-detail-item">编码：{{ selectedFormatDetail.vcodec }}</span>
        <span v-if="selectedFormatDetail.fps" class="format-detail-item">{{ selectedFormatDetail.fps }}fps</span>
        <span v-if="!isSidebar && selectedFormatDetail.tbr" class="format-detail-item">{{ selectedFormatDetail.tbr }}kbps</span>
        <button
          type="button"
          @click="emit('download')"
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
    </div>
  </component>
</template>

<style scoped>
.download-tools--sidebar {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.025);
  overflow: hidden;
}

.download-tools--sidebar[open] {
  background: rgba(255, 255, 255, 0.035);
}

.sidebar-download-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.75rem 0.875rem;
  color: var(--text-secondary);
  font-size: 0.875rem;
  font-weight: 700;
  cursor: pointer;
  list-style: none;
}

.sidebar-download-summary::-webkit-details-marker {
  display: none;
}

.sidebar-download-summary::after {
  content: '';
  width: 8px;
  height: 8px;
  border-right: 2px solid var(--text-muted);
  border-bottom: 2px solid var(--text-muted);
  transform: rotate(45deg);
  transition: transform 0.2s;
}

.download-tools--sidebar[open] .sidebar-download-summary::after {
  transform: rotate(225deg);
}

.sidebar-download-meta {
  margin-left: auto;
  color: var(--accent-cyan);
  font-size: 0.75rem;
  font-weight: 600;
}

.download-tools--sidebar .download-tools-content {
  padding: 0 0.875rem 0.875rem;
}

.parts-section,
.format-section,
.subtitle-section {
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

.parts-label,
.format-label {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.format-label {
  margin-bottom: 0.75rem;
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

.select-all-button,
.download-selected-button,
.download-all-button {
  padding: 0.375rem 0.75rem;
  border-radius: 8px;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.select-all-button {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  font-weight: 500;
}

.select-all-button:hover {
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

.download-selected-button {
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.2);
  color: #93C5FD;
}

.download-selected-button:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.2);
}

.download-all-button {
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.2);
  color: #6EE7B7;
}

.download-all-button:hover:not(:disabled) {
  background: rgba(16, 185, 129, 0.2);
  border-color: rgba(16, 185, 129, 0.4);
}

.download-selected-button:disabled,
.download-all-button:disabled {
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

.parts-list--sidebar {
  max-height: 180px;
}

.part-row {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  border-radius: 8px;
  transition: background 0.15s;
  min-height: 44px;
}

.part-row:hover,
.part-row.active,
.part-row.selected {
  background: rgba(59, 130, 246, 0.1);
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
  background: transparent;
  padding: 0;
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

.part-filesize,
.part-duration,
.format-detail-item,
.progress-info,
.progress-error {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.part-duration {
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
  margin-left: auto;
  padding-left: 0.5rem;
}

.format-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.625rem;
}

.format-grid--sidebar {
  grid-template-columns: 1fr;
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

.subtitle-expanded {
  margin-top: 0.5rem;
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

.subtitle-translate-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.subtitle-translate-hint,
.subtitle-group-label {
  font-size: 0.8125rem;
  color: var(--text-primary);
  white-space: nowrap;
}

.subtitle-group-label {
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 0.375rem;
}

.subtitle-lang-select {
  padding: 0.375rem 2rem 0.375rem 0.75rem;
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

.format-detail {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border);
}

.format-detail--sidebar {
  align-items: flex-start;
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

.format-detail--sidebar .download-btn-inline {
  width: 100%;
  justify-content: center;
  margin-left: 0;
}

.download-btn-inline:hover:not(:disabled) {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.3) 0%, rgba(6, 182, 212, 0.25) 100%);
  border-color: rgba(59, 130, 246, 0.5);
  transform: translateY(-1px);
}

.download-btn-inline:disabled {
  opacity: 0.4;
  cursor: not-allowed;
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

.progress-error {
  color: #FCA5A5;
}

@media (max-width: 768px) {
  .format-grid {
    grid-template-columns: 1fr;
  }

  .format-button {
    padding: 0.625rem 0.75rem;
    min-height: 44px;
  }

  .parts-section {
    font-size: 0.8125rem;
  }

  .part-row {
    padding: 0.5rem;
  }

  .part-title {
    font-size: 0.8125rem;
  }
}
</style>
