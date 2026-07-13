<script setup>
import { ref, watch } from 'vue'
import { formatDuration, formatViewCount } from '../utils/resultFormatters.js'

const props = defineProps({
  videoInfo: { type: Object, required: true },
  currentPartInfo: { type: Object, default: null },
  collapsed: { type: Boolean, default: false },
  showFullDescription: { type: Boolean, default: false },
  variant: { type: String, default: 'mobile' },
  collapsible: { type: Boolean, default: false },
})

const emit = defineEmits(['open-video', 'update:collapsed', 'update:showFullDescription'])
const mobileExpanded = ref(!props.collapsible)

watch(() => props.videoInfo?.webpage_url || props.videoInfo?.title, () => {
  mobileExpanded.value = !props.collapsible
})

function openVideo() {
  if (props.videoInfo.stream_url) emit('open-video')
}
</script>

<template>
  <div v-if="variant === 'sidebar' && collapsed" class="desktop-sidebar-rail">
    <button
      type="button"
      class="desktop-sidebar-rail-control"
      aria-label="展开视频侧栏"
      :aria-expanded="false"
      title="展开视频侧栏"
      @click="emit('update:collapsed', false)"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/>
      </svg>
    </button>
    <button
      type="button"
      class="desktop-sidebar-rail-thumb"
      :class="{ clickable: videoInfo.stream_url }"
      :title="videoInfo.title || '当前视频'"
      @click="videoInfo.stream_url ? openVideo() : emit('update:collapsed', false)"
    >
      <img v-if="videoInfo.thumbnail" :src="videoInfo.thumbnail" :alt="videoInfo.title || '视频缩略图'" />
      <svg v-else viewBox="0 0 24 24" fill="currentColor">
        <path d="M8 5v14l11-7z"/>
      </svg>
    </button>
    <span v-if="currentPartInfo && currentPartInfo.index > 1" class="desktop-sidebar-rail-badge">
      P{{ currentPartInfo.index }}
    </span>
    <button
      type="button"
      class="desktop-sidebar-rail-action"
      title="展开下载工具"
      @click="emit('update:collapsed', false)"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 11l5 5m0 0l5-5m-5 5V3"/>
      </svg>
    </button>
  </div>

  <div v-else class="video-card video-context-panel" :class="{ 'video-context-panel--sidebar': variant === 'sidebar' }">
    <button
      v-if="variant === 'sidebar'"
      type="button"
      class="desktop-sidebar-toggle"
      aria-label="收起视频侧栏"
      :aria-expanded="true"
      title="收起视频侧栏"
      @click="emit('update:collapsed', true)"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7"/>
      </svg>
    </button>

    <button
      v-if="variant === 'mobile' && collapsible"
      type="button"
      class="mobile-context-toggle"
      :aria-expanded="mobileExpanded"
      @click="mobileExpanded = !mobileExpanded"
    >
      <span class="mobile-context-toggle__copy">
        <strong>{{ videoInfo.title }}</strong>
        <span>{{ currentPartInfo?.index ? `P${currentPartInfo.index} · ` : '' }}{{ videoInfo.extractor }}</span>
      </span>
      <svg :class="{ rotated: mobileExpanded }" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
        <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/>
      </svg>
    </button>

    <div v-if="!collapsible || mobileExpanded" class="video-info" :class="{ 'video-info--sidebar': variant === 'sidebar' }">
      <button
        type="button"
        class="video-thumbnail-wrapper"
        :class="{ clickable: videoInfo.stream_url, 'video-thumbnail-wrapper--sidebar': variant === 'sidebar' }"
        :disabled="!videoInfo.stream_url"
        :aria-label="videoInfo.stream_url ? `播放 ${videoInfo.title}` : undefined"
        @click="openVideo"
      >
        <img v-if="videoInfo.thumbnail" :src="videoInfo.thumbnail" :alt="videoInfo.title || '视频缩略图'" class="video-thumbnail" />
        <div v-if="videoInfo.stream_url" class="video-thumbnail-play">
          <svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
        </div>
        <span v-if="videoInfo.duration_string" class="video-thumbnail-duration">
          {{ currentPartInfo?.duration ? formatDuration(currentPartInfo.duration) : videoInfo.duration_string }}
        </span>
      </button>

      <div class="video-details">
        <h3 class="video-title">
          {{ videoInfo.title }}
          <span v-if="currentPartInfo && currentPartInfo.index > 1" class="part-badge">P{{ currentPartInfo.index }}</span>
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

    <div v-if="videoInfo.description && (!collapsible || mobileExpanded)" class="video-description" :class="{ expanded: showFullDescription }">
      <p class="video-description-text">{{ videoInfo.description }}</p>
      <button
        v-if="videoInfo.description.length > 150"
        type="button"
        class="description-toggle"
        @click="emit('update:showFullDescription', !showFullDescription)"
      >
        {{ showFullDescription ? '收起' : '展开全部' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.video-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 2rem;
  backdrop-filter: blur(12px);
}

.video-context-panel--sidebar {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow: visible;
  padding: 1rem;
  border-radius: 12px;
}

.mobile-context-toggle {
  width: 100%;
  min-height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
}

.mobile-context-toggle__copy {
  min-width: 0;
  display: grid;
  gap: 0.25rem;
}

.mobile-context-toggle__copy strong,
.mobile-context-toggle__copy span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-context-toggle__copy strong {
  font-size: 0.9375rem;
}

.mobile-context-toggle__copy span {
  color: var(--text-secondary);
  font-size: 0.75rem;
}

.mobile-context-toggle svg {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  color: var(--text-muted);
  transition: transform 0.2s ease;
}

.mobile-context-toggle svg.rotated {
  transform: rotate(180deg);
}

.desktop-sidebar-toggle {
  position: absolute;
  top: 1.125rem;
  right: -17px;
  z-index: 2;
  width: 34px;
  height: 46px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 999px;
  box-shadow: 0 14px 28px rgba(0, 0, 0, 0.22);
  color: var(--text-secondary);
  cursor: pointer;
  transition: transform 0.15s ease, background 0.15s, color 0.15s, border-color 0.15s;
}

.desktop-sidebar-toggle:hover {
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
  color: var(--text-primary);
  transform: translateX(-2px);
}

.desktop-sidebar-toggle svg {
  width: 17px;
  height: 17px;
}

.desktop-sidebar-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.875rem;
  width: 96px;
  min-height: 238px;
  padding: 0.875rem 0.625rem;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  backdrop-filter: blur(12px);
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.16);
}

.desktop-sidebar-rail-control,
.desktop-sidebar-rail-action {
  width: 52px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border-radius: 12px;
  cursor: pointer;
  transition: transform 0.15s ease, background 0.15s, border-color 0.15s, color 0.15s;
}

.desktop-sidebar-rail-control {
  height: 40px;
  background: rgba(59, 130, 246, 0.12);
  border: 1px solid rgba(59, 130, 246, 0.22);
  color: #93C5FD;
}

.desktop-sidebar-rail-control:hover {
  transform: translateX(2px);
  background: rgba(59, 130, 246, 0.18);
  border-color: rgba(59, 130, 246, 0.36);
  color: #BFDBFE;
}

.desktop-sidebar-rail-action {
  height: 44px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--border);
  color: var(--text-muted);
}

.desktop-sidebar-rail-action:hover {
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
  color: var(--text-primary);
  transform: translateY(-1px);
}

.desktop-sidebar-rail-control svg,
.desktop-sidebar-rail-action svg {
  width: 18px;
  height: 18px;
}

.desktop-sidebar-rail-thumb {
  width: 58px;
  height: 58px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--border);
  border-radius: 14px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: transform 0.15s ease, border-color 0.15s, filter 0.15s;
}

.desktop-sidebar-rail-thumb:hover {
  border-color: var(--border-hover);
  filter: brightness(1.08);
  transform: translateY(-1px);
}

.desktop-sidebar-rail-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.desktop-sidebar-rail-thumb svg {
  width: 22px;
  height: 22px;
}

.desktop-sidebar-rail-badge {
  display: inline-flex;
  min-width: 52px;
  justify-content: center;
  padding: 0.25rem 0.5rem;
  background: rgba(59, 130, 246, 0.15);
  border: 1px solid rgba(59, 130, 246, 0.25);
  border-radius: 999px;
  color: #93C5FD;
  font-size: 0.75rem;
  font-weight: 800;
}

.video-info {
  display: flex;
  gap: 1.25rem;
  margin-bottom: 1.25rem;
}

.video-info--sidebar {
  flex-direction: column;
  gap: 0.875rem;
  margin-bottom: 0;
}

.video-thumbnail-wrapper {
  position: relative;
  width: 220px;
  flex-shrink: 0;
  border-radius: var(--radius);
  overflow: hidden;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
}

.video-thumbnail-wrapper:disabled {
  cursor: default;
}

.video-thumbnail-wrapper--sidebar {
  width: 100%;
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

.video-thumbnail-wrapper--sidebar .video-thumbnail {
  height: auto;
  aspect-ratio: 16 / 9;
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

.video-context-panel--sidebar .video-description {
  margin-bottom: 0;
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
  padding: 0.25rem 0.5rem;
  background: none;
  border: none;
  color: var(--accent-blue);
  font-size: 0.75rem;
  cursor: pointer;
  min-height: 44px;
  line-height: 44px;
}

.description-toggle:hover {
  color: var(--accent-cyan);
}

@media (max-width: 768px) {
  .video-card {
    padding: 1rem;
    border-radius: 12px;
  }

  .video-info {
    flex-direction: column;
    gap: 0.75rem;
  }

  .video-thumbnail-wrapper {
    width: 100%;
  }

  .video-thumbnail {
    width: 100%;
    height: auto;
  }

  .video-thumbnail-play {
    opacity: 1;
  }

  .video-title {
    font-size: 0.9375rem;
  }

  .video-meta-row {
    flex-wrap: wrap;
    gap: 0.375rem;
  }

  .video-meta-item,
  .video-original-link {
    font-size: 0.75rem;
  }
}
</style>
