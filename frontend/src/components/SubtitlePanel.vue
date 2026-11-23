<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
const props = defineProps({
  text: String, info: Object, title: String, busy: Boolean, error: String,
  currentTime: Number, onFetch: Function, onSeek: Function, onClear: Function, cleared: Boolean,
})
const expanded = ref(true)
const copied = ref(false)
const previewId = useId()
const tooltipId = useId()
const hoveredTip = ref(null)
const focusedTip = ref(null)
const tooltipDismissed = ref(false)
const activeTooltip = computed(() => tooltipDismissed.value ? null : hoveredTip.value || focusedTip.value)
const tooltipElement = ref(null)
const tooltipPosition = ref({})
let tooltipTimer
watch([() => props.text, () => props.title], () => {
  copied.value = false
  if (props.text) expanded.value = true
  dismissTooltip()
})
const source = computed(() => ({ bilibili_cc: 'B站 CC', ytdlp_native: '平台字幕', youtube_auto: '平台字幕', whisper: '语音转录' }[props.info?.source] || '已保存字幕'))
const language = computed(() => {
  const raw = (props.info?.language || '').toLowerCase().replaceAll('_', '-')
  const code = raw.startsWith('ai-') ? raw.slice(3) : raw
  const label = code.startsWith('zh-hant') || code === 'zh-tw' ? '繁体中文'
    : code.startsWith('zh') ? '简体中文'
      : code.startsWith('en') ? '英语'
        : code.startsWith('ja') ? '日语'
          : code.startsWith('ko') ? '韩语' : props.info?.language || '语言未知'
  return `${label}${raw.startsWith('ai-') ? ' · 自动' : ''}`
})
const timed = computed(() => props.info?.segments?.length > 0 && props.info.segments.every(s => Number.isFinite(s.start) && Number.isFinite(s.end) && s.end > s.start))
const actions = computed(() => [
  { id: 'copy', label: copied.value ? '已复制' : '复制全文', description: '复制原始字幕全文，方便粘贴到笔记或文档。' },
  { id: 'txt', label: '下载 TXT', description: '纯文本格式，适合阅读、整理笔记和导入文档。' },
  ...(timed.value ? [
    { id: 'srt', label: '下载 SRT', description: '含时间轴的通用字幕格式，适合导入播放器或剪辑软件。' },
    { id: 'vtt', label: '下载 VTT', description: '含时间轴的网页字幕格式，适合网页视频和浏览器播放。' },
  ] : []),
])
function showTooltip(action, event, focused = false) {
  clearTimeout(tooltipTimer)
  const tip = { ...action, element: event.currentTarget }
  if (focused) focusedTip.value = tip
  else hoveredTip.value = tip
  tooltipDismissed.value = false
}
async function positionTooltip(tip) {
  if (!tip) return
  const rect = tip.element.getBoundingClientRect()
  const width = Math.min(252, window.innerWidth - 24)
  tooltipPosition.value = { width: `${width}px`, left: `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`, top: `${rect.bottom + 8}px` }
  await nextTick()
  if (activeTooltip.value !== tip) return
  const height = tooltipElement.value?.offsetHeight || 0
  if (rect.bottom + 8 + height > window.innerHeight - 12) {
    tooltipPosition.value.top = `${Math.max(12, rect.top - height - 8)}px`
  }
}
watch(activeTooltip, positionTooltip)
function repositionTooltip() { positionTooltip(activeTooltip.value) }
function leaveTooltip() {
  clearTimeout(tooltipTimer)
  tooltipTimer = setTimeout(() => { hoveredTip.value = null }, 120)
}
function keepTooltip() { clearTimeout(tooltipTimer) }
function dismissTooltip() {
  clearTimeout(tooltipTimer)
  tooltipDismissed.value = true
}
onMounted(() => {
  window.addEventListener('scroll', repositionTooltip, true)
  window.addEventListener('resize', repositionTooltip)
})
onUnmounted(() => {
  clearTimeout(tooltipTimer)
  window.removeEventListener('scroll', repositionTooltip, true)
  window.removeEventListener('resize', repositionTooltip)
})
const lines = computed(() => props.info?.segments?.length ? props.info.segments : (props.text || '').split('\n').filter(Boolean).map(text => ({ text })))
function timestamp(seconds) {
  const value = Math.floor(seconds)
  return `${Math.floor(value / 60).toString().padStart(2, '0')}:${(value % 60).toString().padStart(2, '0')}`
}
function time(seconds, format) {
  const ms = Math.round(seconds * 1000)
  return `${String(Math.floor(ms / 3600000)).padStart(2, '0')}:${String(Math.floor(ms / 60000) % 60).padStart(2, '0')}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}${format === 'srt' ? ',' : '.'}${String(ms % 1000).padStart(3, '0')}`
}
function download(format) {
  if (format !== 'txt' && !timed.value) return
  let text = props.text
  if (format !== 'txt') {
    text = (format === 'vtt' ? 'WEBVTT\n\n' : '') + props.info.segments.map((s, i) =>
      `${format === 'srt' ? `${i + 1}\n` : ''}${time(s.start, format)} --> ${time(s.end, format)}\n${s.text}\n`).join('\n')
  }
  const url = URL.createObjectURL(new Blob([text], { type: format === 'vtt' ? 'text/vtt;charset=utf-8' : 'text/plain;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${(props.title || '字幕').replace(/[\\/:*?"<>|]/g, '_')}.${format}`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function copy() {
  try {
    await navigator.clipboard.writeText(props.text)
    copied.value = true
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = props.text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    copied.value = document.execCommand('copy')
    textarea.remove()
  }
}
</script>

<template>
  <section class="subtitle-panel" :class="{ expanded }" aria-label="字幕与转录">
    <div class="panel-heading">
      <div class="heading-copy">
        <h2>字幕与转录</h2>
        <p>{{ text ? `${source} · ${language} · ${lines.length} 条` : cleared ? '字幕已清空，不会自动重新获取' : '尚未获取视频字幕' }}</p>
      </div>
      <div class="heading-actions">
        <button v-if="!text" class="tool-button" type="button" :disabled="busy" @click="onFetch?.()">{{ busy ? '正在获取…' : error ? '重试获取字幕' : '获取字幕' }}</button>
        <template v-else>
          <button type="button" class="refresh-button tool-button" :disabled="busy" @click="onFetch?.(true)">{{ info?.source === 'whisper' ? '重新识别' : '重新获取' }}</button>
          <button type="button" class="toggle-button tool-button" :aria-expanded="expanded" :aria-controls="previewId" @click="expanded = !expanded">{{ expanded ? '收起字幕' : '展开字幕' }}</button>
        </template>
      </div>
    </div>
    <p v-if="error" class="error-message" role="alert">{{ error }}</p>
    <template v-if="text">
      <div class="subtitle-actions" role="group" aria-label="复制与下载字幕" @keydown.esc="dismissTooltip">
        <button class="tool-button" v-for="action in actions" :key="action.id" type="button"
          :aria-describedby="activeTooltip?.id === action.id ? tooltipId : undefined"
          @mouseenter="showTooltip(action, $event)" @mouseleave="leaveTooltip"
          @focus="showTooltip(action, $event, true)" @blur="focusedTip = null"
          @click="action.id === 'copy' ? copy() : download(action.id)">{{ action.label }}</button>
        <button v-if="onClear" type="button" class="clear-button tool-button" :disabled="busy" title="清空当前身份的字幕记录和有字幕标记，保留已整理资料；需要时可重新获取。" @click="onClear()">清空字幕</button>
        <span v-if="!timed">无完整时间信息，提供纯文本下载</span>
      </div>
      <span v-if="copied" class="sr-only" role="status">字幕全文已复制</span>
      <div v-if="expanded" :id="previewId" class="subtitle-preview" tabindex="0" aria-label="字幕正文">
        <div v-for="(line, index) in lines" :key="index" class="subtitle-line" :class="{ current: Number.isFinite(line.start) && currentTime >= line.start && currentTime < line.end }">
          <button v-if="Number.isFinite(line.start)" type="button" :aria-label="`跳转到 ${timestamp(line.start)}`" @click="onSeek?.(line.start)">{{ timestamp(line.start) }}</button>
          <span>{{ line.text }}</span>
        </div>
      </div>
    </template>
    <Teleport to="body">
      <div v-if="activeTooltip" :id="tooltipId" ref="tooltipElement" class="subtitle-format-tooltip"
        role="tooltip" :style="tooltipPosition" @mouseenter="keepTooltip" @mouseleave="leaveTooltip">{{ activeTooltip.description }}</div>
    </Teleport>
  </section>
</template>

<style scoped>
.subtitle-panel { min-width: 0; padding: .75rem .9rem; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-secondary); }
.subtitle-panel.expanded { padding-bottom: .85rem; }
.panel-heading { display: flex; justify-content: space-between; align-items: center; gap: .75rem; min-height: 38px; }
.heading-copy { min-width: 0; }
h2 { font-size: .9375rem; font-weight: 650; color: var(--text-primary); margin: 0; }
p { color: var(--text-secondary); font-size: .75rem; margin: .15rem 0 0; line-height: 1.45; }
.heading-actions { display: flex; align-items: center; gap: .4rem; flex-shrink: 0; }
button { min-height: 36px; padding: .35rem .65rem; border: 1px solid var(--border); border-radius: 6px; color: var(--text-primary); background: var(--bg-primary); cursor: pointer; flex-shrink: 0; font-size: .8125rem; }
button:hover { border-color: var(--accent-blue); }
button:disabled { opacity: .5; cursor: wait; }
button:focus-visible, .subtitle-preview:focus-visible { outline: 2px solid var(--accent-blue); outline-offset: 3px; }
.subtitle-actions { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem; margin: .6rem 0; font-size: .6875rem; color: var(--text-secondary); }
.subtitle-actions button { min-height: 44px; }
.subtitle-preview { max-height: min(42vh, 360px); overflow: auto; padding: .25rem 0; font-size: .8125rem; line-height: 1.55; }
.subtitle-line { display: flex; align-items: baseline; gap: .55rem; padding: .12rem .25rem; white-space: pre-wrap; overflow-wrap: anywhere; border-radius: 4px; }
.subtitle-line.current { background: color-mix(in srgb, var(--accent-blue) 15%, transparent); }
.subtitle-line button { min-height: auto; background: transparent; border: 0; color: var(--accent-blue); padding: 0 .15rem; font-variant-numeric: tabular-nums; text-decoration: underline; text-underline-offset: 2px; }
.error-message { color: #fca5a5; }
.subtitle-format-tooltip { position: fixed; z-index: 200; padding: .65rem .8rem; border: 1px solid var(--border-hover); border-radius: 8px; background: var(--text-primary); color: var(--bg-primary); box-shadow: 0 6px 20px rgb(0 0 0 / .2); font-size: .8125rem; line-height: 1.6; overflow-wrap: anywhere; }
@media (max-width: 640px) { .subtitle-panel { padding: .65rem .7rem; } .panel-heading { align-items: flex-start; flex-wrap: wrap; min-height: 42px; } .heading-actions { gap: .2rem; } button { min-height: 44px; } .subtitle-actions { gap: .5rem; } }
</style>
