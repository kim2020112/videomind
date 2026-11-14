<script setup>
import { ref, watch, nextTick, onUnmounted } from 'vue'
import { useAuth } from '../composables/useAuth.js'
import BaseDialog from './BaseDialog.vue'

const props = defineProps({
  streamUrl: String,
  audioStreamUrl: String,
  streamNeedsAudio: Boolean,
  streamExpiresAt: { type: Number, default: 0 },
  playbackRate: { type: Number, default: 1 },
  videoTitle: String,
  visible: Boolean,
  videoUrl: String,
})

const emit = defineEmits(['close', 'seek', 'playback-rate-change'])
const videoRef = ref(null)
const audioRef = ref(null)
const currentUrl = ref('')
const currentAudioUrl = ref('')
const isRefreshing = ref(false)
const loadError = ref(false)
const audioBlocked = ref(false)
const isPlaying = ref(false)
const pendingSeek = ref(null)
const resumeAfterLoad = ref(false)
const { getAuthHeaders, getAuthQueryParams } = useAuth()
const rates = [1, 1.5, 2]

function toProxyUrl(rawUrl) {
  if (!rawUrl) return ''
  let proxy = `/api/video/stream?url=${encodeURIComponent(rawUrl)}`
  if (props.videoUrl) proxy += `&video_url=${encodeURIComponent(props.videoUrl)}`
  for (const [key, value] of getAuthQueryParams()) proxy += `&${encodeURIComponent(key)}=${encodeURIComponent(value)}`
  return proxy
}

function syncAudioTime() {
  if (!audioRef.value || !videoRef.value) return
  if (Math.abs(audioRef.value.currentTime - videoRef.value.currentTime) > 0.15) {
    audioRef.value.currentTime = videoRef.value.currentTime
  }
}

function applyRate(rate = props.playbackRate) {
  if (videoRef.value) videoRef.value.playbackRate = rate
  if (audioRef.value) audioRef.value.playbackRate = rate
}

async function playMedia() {
  if (!videoRef.value) return
  audioBlocked.value = false
  applyRate()
  syncAudioTime()
  try {
    await videoRef.value.play()
    if (audioRef.value) await audioRef.value.play()
    isPlaying.value = true
  } catch (error) {
    if (audioRef.value && error) {
      videoRef.value.pause()
      audioBlocked.value = true
      isPlaying.value = false
    }
  }
}

function pauseMedia() {
  videoRef.value?.pause()
  audioRef.value?.pause()
  isPlaying.value = false
}

function onPlay() {
  if (audioRef.value && audioRef.value.paused) {
    syncAudioTime()
    audioRef.value.play().catch(() => {
      videoRef.value?.pause()
      audioBlocked.value = true
      isPlaying.value = false
    })
  }
  isPlaying.value = true
}
function onPause() { audioRef.value?.pause(); isPlaying.value = false }
function onSeeking() { syncAudioTime() }
function onTimeUpdate() {
  syncAudioTime()
  if (videoRef.value) emit('seek', videoRef.value.currentTime)
}
function onVolumeChange() {
  if (!videoRef.value || !audioRef.value) return
  audioRef.value.volume = videoRef.value.volume
  audioRef.value.muted = videoRef.value.muted
}
function onEnded() { audioRef.value?.pause(); isPlaying.value = false }

async function onVideoError() {
  if (isRefreshing.value || !props.videoUrl) return
  const video = videoRef.value
  const snapshot = video ? { time: video.currentTime, paused: video.paused, volume: video.volume, muted: video.muted, rate: video.playbackRate } : null
  isRefreshing.value = true
  loadError.value = false
  try {
    const params = new URLSearchParams({ url: props.videoUrl })
    const response = await fetch(`/api/video/refresh?${params}`, { headers: getAuthHeaders(), credentials: 'same-origin' })
    const data = await response.json()
    if (!data.stream_url) throw new Error('no stream')
    currentUrl.value = toProxyUrl(data.stream_url)
    currentAudioUrl.value = data.audio_stream_url && data.stream_needs_audio ? toProxyUrl(data.audio_stream_url) : ''
    if (snapshot) {
      pendingSeek.value = snapshot.time
      resumeAfterLoad.value = !snapshot.paused
    }
    if (videoRef.value && snapshot) {
      videoRef.value.volume = snapshot.volume
      videoRef.value.muted = snapshot.muted
      applyRate(snapshot.rate)
    }
  } catch { loadError.value = true } finally { isRefreshing.value = false }
}

function seekTo(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return
  pendingSeek.value = seconds
  resumeAfterLoad.value = true
  applyPendingSeek()
}

function applyPendingSeek() {
  const video = videoRef.value
  if (!video || pendingSeek.value === null || video.readyState < 1) return
  try {
    video.currentTime = pendingSeek.value
    pendingSeek.value = null
  } catch { return }
  syncAudioTime()
  if (resumeAfterLoad.value) {
    resumeAfterLoad.value = false
    playMedia()
  }
}
function setRate(rate) {
  emit('playback-rate-change', rate)
  applyRate(rate)
}

watch(() => props.visible, visible => {
  if (visible) {
    currentUrl.value = toProxyUrl(props.streamUrl)
    currentAudioUrl.value = props.streamNeedsAudio ? toProxyUrl(props.audioStreamUrl) : ''
    loadError.value = false
    audioBlocked.value = false
    nextTick(() => {
      applyRate()
      const expired = props.streamExpiresAt > 0 && props.streamExpiresAt <= Date.now() / 1000 + 60
      if (!props.streamUrl || expired) onVideoError()
    })
  } else pauseMedia()
}, { immediate: true })
watch(() => [props.streamUrl, props.audioStreamUrl, props.streamNeedsAudio], () => {
  if (props.visible) {
    currentUrl.value = toProxyUrl(props.streamUrl)
    currentAudioUrl.value = props.streamNeedsAudio ? toProxyUrl(props.audioStreamUrl) : ''
  }
})
watch(() => props.playbackRate, value => applyRate(value))
onUnmounted(pauseMedia)
defineExpose({ seekTo })
</script>

<template>
  <BaseDialog :visible="visible" :title-id="'video-player-title'" :close-label="`关闭视频播放器${videoTitle ? `：${videoTitle}` : ''}`" size="video" :close-on-overlay="false" @close="emit('close')">
    <h2 id="video-player-title" class="sr-only">{{ videoTitle || '视频播放器' }}</h2>
    <div v-if="loadError" class="video-modal-status error" role="alert"><p>播放链接已失效</p><button type="button" class="video-modal-retry" @click="onVideoError">重试</button></div>
    <div v-else class="video-stage">
      <div v-if="isRefreshing" class="video-modal-status video-modal-status--loading" aria-live="polite">刷新播放链接…</div>
      <video ref="videoRef" :src="currentUrl" controls autoplay class="video-modal-player" @loadedmetadata="applyPendingSeek" @play="onPlay" @pause="onPause" @seeking="onSeeking" @timeupdate="onTimeUpdate" @volumechange="onVolumeChange" @ended="onEnded" @error="onVideoError" />
      <audio v-if="streamNeedsAudio && currentAudioUrl" ref="audioRef" :src="currentAudioUrl" preload="auto" @error="onVideoError" />
      <div class="rate-control" role="group" aria-label="播放速度">
        <button v-for="rate in rates" :key="rate" type="button" :aria-pressed="playbackRate === rate" @click="setRate(rate)">{{ rate }}×</button>
      </div>
      <button v-if="audioBlocked" type="button" class="audio-enable" @click="playMedia">点击播放以启用声音</button>
    </div>
  </BaseDialog>
</template>

<style scoped>
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
.video-stage { position: relative; width: 100%; height: 100%; }
.video-modal-player { width: 100%; height: 100%; object-fit: contain; }
audio { display: none; }
.video-modal-status { width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: .75rem; color: var(--text-secondary); }
.video-modal-status--loading { position: absolute; inset: 0; z-index: 2; background: rgba(0,0,0,.72); pointer-events: none; }
.video-modal-status.error { color: #fca5a5; }
.video-modal-retry, .audio-enable { min-height: 44px; padding: .5rem 1rem; border: 1px solid rgba(148,163,184,.3); border-radius: 8px; background: rgba(148,163,184,.1); color: var(--text-secondary); cursor: pointer; }
.rate-control { position: absolute; top: .75rem; left: .75rem; display: flex; gap: 2px; }
.rate-control button { min-width: 42px; min-height: 32px; border: 1px solid rgba(255,255,255,.35); background: rgba(0,0,0,.65); color: white; cursor: pointer; }
.rate-control button[aria-pressed="true"] { background: rgba(59,130,246,.9); }
.audio-enable { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); background: rgba(0,0,0,.8); color: white; }
</style>
