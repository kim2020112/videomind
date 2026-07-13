<script setup>
import { ref, watch } from 'vue'
import { useAuth } from '../composables/useAuth.js'
import BaseDialog from './BaseDialog.vue'

const props = defineProps({
  streamUrl: String,
  videoTitle: String,
  visible: Boolean,
  videoUrl: String,
})

const emit = defineEmits(['close', 'seek'])
const videoRef = ref(null)
const currentUrl = ref('')
const isRefreshing = ref(false)
const loadError = ref(false)
const { getAuthHeaders, getAuthQueryParams } = useAuth()

function toProxyUrl(rawUrl) {
  if (!rawUrl) return ''
  let proxy = `/api/video/stream?url=${encodeURIComponent(rawUrl)}`
  if (props.videoUrl) proxy += `&video_url=${encodeURIComponent(props.videoUrl)}`
  for (const [key, value] of getAuthQueryParams()) {
    proxy += `&${encodeURIComponent(key)}=${encodeURIComponent(value)}`
  }
  return proxy
}

watch(() => props.visible, (visible) => {
  if (visible) {
    currentUrl.value = toProxyUrl(props.streamUrl)
    loadError.value = false
  }
})

watch(() => props.streamUrl, (value) => {
  if (value && props.visible) {
    currentUrl.value = toProxyUrl(value)
    loadError.value = false
  }
})

function onTimeUpdate() {
  if (videoRef.value) emit('seek', videoRef.value.currentTime)
}

async function onVideoError() {
  if (isRefreshing.value || !props.videoUrl) return
  isRefreshing.value = true
  loadError.value = false
  try {
    const params = new URLSearchParams({ url: props.videoUrl })
    const response = await fetch(`/api/video/refresh?${params}`, {
      headers: getAuthHeaders(),
      credentials: 'same-origin',
    })
    const data = await response.json()
    if (data.stream_url) {
      currentUrl.value = toProxyUrl(data.stream_url)
    } else {
      loadError.value = true
    }
  } catch {
    loadError.value = true
  } finally {
    isRefreshing.value = false
  }
}

function seekTo(seconds) {
  if (!videoRef.value) return
  videoRef.value.currentTime = seconds
  if (videoRef.value.paused) videoRef.value.play().catch(() => {})
}

defineExpose({ seekTo })
</script>

<template>
  <BaseDialog
    :visible="visible"
    :title-id="'video-player-title'"
    :close-label="`关闭视频播放器${videoTitle ? `：${videoTitle}` : ''}`"
    size="video"
    :close-on-overlay="false"
    @close="emit('close')"
  >
    <h2 id="video-player-title" class="sr-only">{{ videoTitle || '视频播放器' }}</h2>
    <div v-if="isRefreshing" class="video-modal-status" aria-live="polite">刷新播放链接…</div>
    <div v-else-if="loadError" class="video-modal-status error" role="alert">
      <p>播放链接已失效</p>
      <button type="button" class="video-modal-retry" @click="onVideoError">重试</button>
    </div>
    <video
      v-else
      ref="videoRef"
      :src="currentUrl"
      controls
      autoplay
      class="video-modal-player"
      @timeupdate="onTimeUpdate"
      @error="onVideoError"
    />
  </BaseDialog>
</template>

<style scoped>
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.video-modal-player {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.video-modal-status {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  color: var(--text-secondary);
}

.video-modal-status.error {
  color: #fca5a5;
}

.video-modal-retry {
  min-width: 88px;
  min-height: 44px;
  padding: 0.5rem 1rem;
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 8px;
  background: rgba(148, 163, 184, 0.1);
  color: var(--text-secondary);
  cursor: pointer;
}

.video-modal-retry:hover {
  background: rgba(148, 163, 184, 0.2);
}
</style>
