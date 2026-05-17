<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'

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

function toProxyUrl(rawUrl) {
  if (!rawUrl) return ''
  let proxy = `/api/video/stream?url=${encodeURIComponent(rawUrl)}`
  if (props.videoUrl) {
    proxy += `&video_url=${encodeURIComponent(props.videoUrl)}`
  }
  return proxy
}

watch(() => props.visible, (v) => {
  if (v) {
    currentUrl.value = toProxyUrl(props.streamUrl)
    loadError.value = false
    document.body.style.overflow = 'hidden'
  } else {
    document.body.style.overflow = ''
  }
})

watch(() => props.streamUrl, (v) => {
  if (v && props.visible) {
    currentUrl.value = toProxyUrl(v)
    loadError.value = false
  }
})

function onKeydown(e) {
  if (e.key === 'Escape' && props.visible) {
    emit('close')
  }
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})

function onTimeUpdate() {
  if (videoRef.value) {
    emit('seek', videoRef.value.currentTime)
  }
}

async function onVideoError() {
  if (isRefreshing.value || !props.videoUrl) return
  isRefreshing.value = true
  loadError.value = false
  try {
    const resp = await fetch(`/api/video/refresh?url=${encodeURIComponent(props.videoUrl)}`)
    const data = await resp.json()
    if (data.stream_url) {
      currentUrl.value = toProxyUrl(data.stream_url)
      loadError.value = false
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
  if (videoRef.value) {
    videoRef.value.currentTime = seconds
    if (videoRef.value.paused) videoRef.value.play().catch(() => {})
  }
}

defineExpose({ seekTo })
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="video-modal-overlay" @click.self="$emit('close')">
      <div class="video-modal">
        <button class="video-modal-close" @click="$emit('close')" title="关闭 (ESC)">&times;</button>
        <div v-if="isRefreshing" class="video-modal-status">刷新播放链接...</div>
        <div v-else-if="loadError" class="video-modal-status error">
          <p>播放链接已失效</p>
          <button @click="onVideoError" class="video-modal-retry">重试</button>
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
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.video-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}
.video-modal {
  position: relative;
  width: min(80vw, 1200px);
  aspect-ratio: 16 / 9;
  border-radius: 12px;
  overflow: hidden;
  background: #000;
}
.video-modal-player {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.video-modal-close {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  z-index: 10;
  width: 2rem;
  height: 2rem;
  border: none;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-size: 1.25rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}
.video-modal-close:hover {
  background: rgba(0, 0, 0, 0.8);
}
.video-modal-status {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  gap: 0.75rem;
}
.video-modal-status.error {
  color: #fca5a5;
}
.video-modal-retry {
  padding: 0.375rem 1rem;
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 6px;
  background: rgba(148, 163, 184, 0.1);
  color: #94a3b8;
  cursor: pointer;
  font-size: 0.875rem;
}
.video-modal-retry:hover {
  background: rgba(148, 163, 184, 0.2);
}
@media (max-width: 768px) {
  .video-modal {
    width: 100vw;
    border-radius: 0;
  }
}
</style>
