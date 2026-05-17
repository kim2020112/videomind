<script setup>
import { computed, ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { Transformer } from 'markmap-lib'
import { Markmap } from 'markmap-view'

marked.setOptions({ gfm: true, breaks: true })

function renderMarkdown(text) {
  if (!text) return ''
  return DOMPurify.sanitize(marked.parse(text))
}

function renderNotesMarkdown(text) {
  if (!text) return ''
  let html = DOMPurify.sanitize(marked.parse(text), { ADD_ATTR: ['data-seconds'] })
  // 字符串层面替换 [MM:SS] 为可点击 span（跳过 <code> 块内的）
  html = html.replace(
    /(<code[\s\S]*?<\/code>|<pre[\s\S]*?<\/pre>)|\[(\d{1,2}:\d{2}(?::\d{2})?)\]/g,
    (match, codeBlock, ts) => {
      if (codeBlock) return codeBlock
      const parts = ts.split(':').map(Number)
      const sec = parts.length === 3 ? parts[0]*3600+parts[1]*60+parts[2] : parts[0]*60+parts[1]
      return `<span class="notes-timestamp" data-seconds="${sec}">${ts}</span>`
    }
  )
  return html
}

function onNotesClick(e) {
  const ts = e.target.closest('.notes-timestamp')
  if (ts) {
    const sec = parseFloat(ts.dataset.seconds)
    if (!isNaN(sec)) props.onSeekVideo?.(sec)
  }
}

const props = defineProps({
  result: Object,
  loading: Boolean,
  regeneratingMode: String,
  subtitleSource: String,
  error: String,
  streamingText: String,
  subtitleText: String,
  isFetchingSubtitle: Boolean,
  subtitleError: String,
  chatMessages: Array,
  isChatStreaming: Boolean,
  chatError: String,
  subtitleInfo: Object,
  isPartialSummary: Boolean,
  videoTitle: String,
  mindmapMarkdown: String,
  notesMarkdown: String,
  notesSections: Object,
  flashcards: Array,
  generationStage: String,
  multiParts: { type: Array, default: () => [] },
  currentSummarizePart: { type: Number, default: 1 },
  onSummarize: Function,
  onRegenerateSummary: Function,
  onRegenerateMindmap: Function,
  onRegenerateNotes: Function,
  onRegenerateSubtitle: Function,
  onFetchSubtitle: Function,
  onSendQuestion: Function,
  onSwitchPart: Function,
  onSeekVideo: Function,
  currentVideoTime: { type: Number, default: 0 },
})

const isLimitError = computed(() => props.error && props.error.includes('免费次数'))

const activeSubTab = ref('summary')
const chatInput = ref('')
const partsNavScroll = ref(null)
const canScrollLeft = ref(false)
const canScrollRight = ref(false)

function updateScrollState() {
  const el = partsNavScroll.value
  if (!el) return
  canScrollLeft.value = el.scrollLeft > 2
  canScrollRight.value = el.scrollLeft < el.scrollWidth - el.clientWidth - 2
}

function scrollParts(dir) {
  const el = partsNavScroll.value
  if (!el) return
  el.scrollBy({ left: dir * 200, behavior: 'smooth' })
}

// 分P标题 tooltip
const tooltip = ref({ visible: false, text: '', x: 0, y: 0 })
let tooltipTimer = null

function showTooltip(e, text) {
  clearTimeout(tooltipTimer)
  tooltipTimer = setTimeout(() => {
    const rect = e.target.closest('.parts-nav-btn').getBoundingClientRect()
    tooltip.value = {
      visible: true,
      text,
      x: rect.left + rect.width / 2,
      y: rect.top - 8,
    }
  }, 400)
}

function hideTooltip() {
  clearTimeout(tooltipTimer)
  tooltip.value.visible = false
}

watch(() => props.multiParts, () => {
  nextTick(() => updateScrollState())
}, { immediate: true })

const hasMindmap = computed(() => !!props.mindmapMarkdown)
const hasNotes = computed(() => !!props.notesMarkdown)
const hasSubtitle = computed(() => !!props.subtitleText)

const subtitleSegments = computed(() => {
  // 优先使用后端 segments（有精确 start/end 时间）
  const segs = props.subtitleInfo?.segments
  if (segs && segs.length > 0) {
    return segs.map(s => {
      const totalSec = Math.floor(s.start)
      const mm = String(Math.floor(totalSec / 60)).padStart(2, '0')
      const ss = String(totalSec % 60).padStart(2, '0')
      return { time: `${mm}:${ss}`, seconds: s.start, end: s.end, text: s.text }
    })
  }
  // 降级：从文本解析
  if (!props.subtitleText) return []
  let lines = props.subtitleText.split('\n').map(l => l.trim()).filter(l => l.length > 0)
  if (lines.length <= 1 && props.subtitleText.length > 50) {
    let split = props.subtitleText
      .replace(/([。！？；])/g, '$1\n')
      .split('\n')
      .map(l => l.trim())
      .filter(l => l.length > 0)
    if (split.length <= 3) {
      const words = props.subtitleText.split(/\s+/)
      split = []
      let buf = []
      let len = 0
      for (const w of words) {
        if (len + w.length > 40 && buf.length > 0) {
          split.push(buf.join(' '))
          buf = []
          len = 0
        }
        buf.push(w)
        len += w.length + 1
      }
      if (buf.length > 0) split.push(buf.join(' '))
    }
    lines = split
  }
  return lines.map(line => {
    const timeMatch = line.match(/^\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*(.*)/)
    if (timeMatch) {
      return { time: timeMatch[1], seconds: null, end: null, text: timeMatch[2] }
    }
    return { time: null, seconds: null, end: null, text: line }
  })
})

const hasSubtitleSegments = computed(() => subtitleSegments.value.length > 0)

function isActiveSegment(seg) {
  return seg.seconds != null && seg.end != null
    && props.currentVideoTime >= seg.seconds
    && props.currentVideoTime < seg.end
}

// 当前播放字幕自动滚动
const subtitleWrapperRef = ref(null)
watch(() => props.currentVideoTime, () => {
  if (!subtitleWrapperRef.value) return
  const active = subtitleWrapperRef.value.querySelector('.subtitle-segment.active')
  if (active) active.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
})

const showDownloadMenu = ref(false)
const downloadDropdownRef = ref(null)

function toggleDownloadMenu() {
  showDownloadMenu.value = !showDownloadMenu.value
}

function downloadSubtitleFormat(format) {
  subtitleFormat.value = format
  showDownloadMenu.value = false
  downloadSubtitle()
}

function handleClickOutside(e) {
  if (downloadDropdownRef.value && !downloadDropdownRef.value.contains(e.target)) {
    showDownloadMenu.value = false
  }
}

onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => document.removeEventListener('click', handleClickOutside))

function handleStart() {
  props.onSummarize(false)
}

function handleRegenerateSummary() {
  props.onRegenerateSummary()
}

function handleRegenerateMindmap() {
  props.onRegenerateMindmap()
}

function handleRegenerateNotes() {
  props.onRegenerateNotes()
}

function handleRegenerateSubtitle() {
  props.onRegenerateSubtitle()
}

function handleTabSubtitle() {
  activeSubTab.value = 'subtitle'
  if (!props.subtitleText && !props.isFetchingSubtitle && props.onFetchSubtitle) {
    props.onFetchSubtitle()
  }
}

function handleTabQA() {
  activeSubTab.value = 'qa'
  if (!props.subtitleText && !props.isFetchingSubtitle && props.onFetchSubtitle) {
    props.onFetchSubtitle()
  }
}

function sendChat() {
  if (!chatInput.value.trim() || props.isChatStreaming) return
  props.onSendQuestion(chatInput.value)
  chatInput.value = ''
}

// ──── 思维导图 (markmap) ────
const mindmapSvg = ref(null)
const mindmapContainer = ref(null)
const isFullscreen = ref(false)
let markmapInstance = null

const MINDMAP_SVG_STYLE = `
  .markmap-foreign { display: inline-block !important; }
  foreignObject { overflow: visible !important; }
  foreignObject div {
    font-size: 15px !important;
    font-family: 'Noto Sans SC', -apple-system, sans-serif !important;
    color: #F8FAFC !important;
    background: transparent !important;
    padding: 2px 4px !important;
    border-radius: 0 !important;
    line-height: 1.6 !important;
    font-weight: 500 !important;
    text-shadow:
      0 1px 1px rgba(15, 23, 42, 0.95),
      0 0 8px rgba(15, 23, 42, 0.85),
      0 0 16px rgba(15, 23, 42, 0.55) !important;
  }
  .markmap-link {
    stroke: rgba(99, 102, 241, 0.48) !important;
    stroke-width: 2px !important;
  }
  .markmap-node-circle {
    fill: #6366F1 !important;
    stroke: #A5B4FC !important;
    stroke-width: 1.5px !important;
  }
`

function injectMindmapStyle(svgEl) {
  if (!svgEl) return
  svgEl.querySelector('[data-mindmap-theme="true"]')?.remove()
  const styleEl = document.createElementNS('http://www.w3.org/2000/svg', 'style')
  styleEl.setAttribute('data-mindmap-theme', 'true')
  styleEl.textContent = MINDMAP_SVG_STYLE
  svgEl.insertBefore(styleEl, svgEl.firstChild)
}

watch(() => props.mindmapMarkdown, async (val) => {
  if (val) {
    await nextTick()
    renderMindmap(val)
  }
})

function renderMindmap(md) {
  if (!mindmapSvg.value) return
  try {
    mindmapSvg.value.innerHTML = ''
    const transformer = new Transformer()
    const { root } = transformer.transform(md)
    markmapInstance = Markmap.create(mindmapSvg.value, { autoFit: true, duration: 0 }, root)
    injectMindmapStyle(mindmapSvg.value)
  } catch (e) {
    console.warn('思维导图渲染失败:', e)
  }
}

function onFullscreenChange() {
  isFullscreen.value = !!document.fullscreenElement
  nextTick(() => {
    if (markmapInstance) markmapInstance.fit()
  })
}

onMounted(() => document.addEventListener('fullscreenchange', onFullscreenChange))
onUnmounted(() => document.removeEventListener('fullscreenchange', onFullscreenChange))

function toggleFullscreen() {
  if (!mindmapContainer.value) return
  if (!document.fullscreenElement) {
    mindmapContainer.value.requestFullscreen()
  } else {
    document.exitFullscreen()
  }
}

function getSafeFilename() {
  return (props.videoTitle || 'mindmap').replace(/[\\/*?:"<>|]/g, '_').substring(0, 80)
}

const EXPORT_TARGET_LONG_EDGE = 1600
const EXPORT_PNG_LONG_EDGE = 3840
const EXPORT_PADDING = 60
const EXPORT_RENDER_SIZE = 2400
const EXPORT_FONT_FAMILY = 'Microsoft YaHei, PingFang SC, Arial, sans-serif'

function toFiniteNumber(value, fallback = 0) {
  return Number.isFinite(value) ? value : fallback
}

function waitForRenderFrames(count = 2) {
  return new Promise(resolve => {
    const step = () => {
      if (count <= 0) {
        resolve()
        return
      }
      count -= 1
      requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  })
}

async function createExportStage() {
  if (!props.mindmapMarkdown) return null

  const mount = document.createElement('div')
  mount.style.position = 'fixed'
  mount.style.left = '-100000px'
  mount.style.top = '0'
  mount.style.visibility = 'hidden'
  mount.style.pointerEvents = 'none'
  mount.style.overflow = 'hidden'

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.setAttribute('width', String(EXPORT_RENDER_SIZE))
  svg.setAttribute('height', String(EXPORT_RENDER_SIZE))
  svg.setAttribute('viewBox', `0 0 ${EXPORT_RENDER_SIZE} ${EXPORT_RENDER_SIZE}`)

  mount.appendChild(svg)
  document.body.appendChild(mount)

  try {
    const transformer = new Transformer()
    const { root } = transformer.transform(props.mindmapMarkdown)
    const instance = Markmap.create(svg, { autoFit: true, duration: 0 }, root)
    injectMindmapStyle(svg)
    await waitForRenderFrames(2)
    instance.fit?.()
    await waitForRenderFrames(2)
    return { mount, svg, instance }
  } catch (e) {
    mount.remove()
    throw e
  }
}

function cleanupExportStage(stage) {
  stage?.instance?.destroy?.()
  stage?.mount?.remove()
}

function getContentBBox(svgEl) {
  const gRoot = svgEl.querySelector('g')
  if (gRoot) {
    try {
      const bbox = gRoot.getBBox()
      if (bbox.width > 0 && bbox.height > 0) {
        const transform = gRoot.getAttribute('transform') || ''
        const translateMatch = transform.match(/translate\(\s*([-\d.e]+)\s*[,\s]\s*([-\d.e]+)\s*\)/)
        const scaleMatch = transform.match(/scale\(\s*([-\d.e]+)/)
        const tx = translateMatch ? parseFloat(translateMatch[1]) : 0
        const ty = translateMatch ? parseFloat(translateMatch[2]) : 0
        const sc = scaleMatch ? parseFloat(scaleMatch[1]) : 1
        return {
          x: bbox.x * sc + tx,
          y: bbox.y * sc + ty,
          width: bbox.width * sc,
          height: bbox.height * sc,
        }
      }
    } catch {}
  }

  try {
    const bbox = svgEl.getBBox()
    if (bbox.width > 0 && bbox.height > 0) return bbox
  } catch {}

  return { x: 0, y: 0, width: 800, height: 600 }
}

function buildExportableSvg(svgSource) {
  const cloned = svgSource.cloneNode(true)
  cloned.removeAttribute('style')
  cloned.removeAttribute('class')
  Array.from(cloned.attributes)
    .filter(attr => attr.name.startsWith('data-'))
    .forEach(attr => cloned.removeAttribute(attr.name))

  injectMindmapStyle(cloned)

  cloned.querySelectorAll('[transform]').forEach(el => {
    const t = el.getAttribute('transform')
    if (t && t.includes('NaN')) {
      el.setAttribute('transform', 'translate(0,0) scale(1)')
    }
  })

  cloned.querySelectorAll('foreignObject').forEach(fo => {
    const textContent = fo.textContent?.trim() || ''
    if (!textContent) {
      fo.remove()
      return
    }

    const x = parseFloat(fo.getAttribute('x')) || 0
    const y = parseFloat(fo.getAttribute('y')) || 0
    const height = parseFloat(fo.getAttribute('height')) || 28

    const textEl = document.createElementNS('http://www.w3.org/2000/svg', 'text')
    textEl.setAttribute('x', String(x + 6))
    textEl.setAttribute('y', String(y + height / 2 + 1))
    textEl.setAttribute('font-size', '15')
    textEl.setAttribute('font-family', EXPORT_FONT_FAMILY)
    textEl.setAttribute('fill', '#F8FAFC')
    textEl.setAttribute('font-weight', '600')
    textEl.setAttribute('dominant-baseline', 'middle')
    textEl.setAttribute('paint-order', 'stroke fill')
    textEl.setAttribute('stroke', '#0F172A')
    textEl.setAttribute('stroke-opacity', '0.92')
    textEl.setAttribute('stroke-width', '3')
    textEl.setAttribute('stroke-linejoin', 'round')
    textEl.textContent = textContent

    fo.parentNode.replaceChild(textEl, fo)
  })

  return cloned
}

function ensureExportBackground(svgClone, { vx, vy, vw, vh }) {
  const oldBg = svgClone.querySelector('[data-export-background="true"]')
  oldBg?.remove()
  const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
  bg.setAttribute('data-export-background', 'true')
  bg.setAttribute('x', String(vx))
  bg.setAttribute('y', String(vy))
  bg.setAttribute('width', String(vw))
  bg.setAttribute('height', String(vh))
  bg.setAttribute('fill', '#0F172A')
  svgClone.insertBefore(bg, svgClone.firstChild)
}

function serializeSvg(svgEl) {
  const serializer = new XMLSerializer()
  let svgString = serializer.serializeToString(svgEl)
  if (!svgString.includes('xmlns=')) {
    svgString = svgString.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"')
  }
  return svgString
}

function setExportViewBox(svgClone, dims, targetLongEdge = EXPORT_TARGET_LONG_EDGE) {
  const safeX = toFiniteNumber(dims.x, 0)
  const safeY = toFiniteNumber(dims.y, 0)
  const safeWidth = Math.max(toFiniteNumber(dims.width, 800), 1)
  const safeHeight = Math.max(toFiniteNumber(dims.height, 600), 1)

  const vx = Math.floor(safeX - EXPORT_PADDING)
  const vy = Math.floor(safeY - EXPORT_PADDING)
  const vw = Math.max(Math.ceil(safeWidth + EXPORT_PADDING * 2), 1)
  const vh = Math.max(Math.ceil(safeHeight + EXPORT_PADDING * 2), 1)

  svgClone.setAttribute('viewBox', `${vx} ${vy} ${vw} ${vh}`)
  svgClone.setAttribute('preserveAspectRatio', 'xMidYMid meet')

  const displayScale = targetLongEdge / Math.max(vw, vh)
  const displayWidth = Math.max(Math.round(vw * displayScale), 1)
  const displayHeight = Math.max(Math.round(vh * displayScale), 1)
  svgClone.setAttribute('width', String(displayWidth))
  svgClone.setAttribute('height', String(displayHeight))

  ensureExportBackground(svgClone, { vx, vy, vw, vh })
  return { vw, vh }
}

async function downloadSVG() {
  const stage = await createExportStage()
  if (!stage) return

  try {
    const dims = getContentBBox(stage.svg)
    const exportSvg = buildExportableSvg(stage.svg)
    setExportViewBox(exportSvg, dims)
    exportSvg.setAttribute('width', '100%')
    exportSvg.removeAttribute('height')
    exportSvg.setAttribute('style', 'display:block;background:#0F172A;max-width:100%;height:auto;')
    const svgString = serializeSvg(exportSvg)
    const blob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' })
    triggerDownload(blob, `${getSafeFilename()} - 思维导图.svg`)
  } catch (e) {
    console.warn('SVG 导出失败:', e)
  } finally {
    cleanupExportStage(stage)
  }
}

async function downloadPNG() {
  const stage = await createExportStage()
  if (!stage) return

  try {
    const dims = getContentBBox(stage.svg)
    const exportSvg = buildExportableSvg(stage.svg)
    const { vw, vh } = setExportViewBox(exportSvg, dims)
    const scale = Math.max(1, Math.ceil(EXPORT_PNG_LONG_EDGE / Math.max(vw, vh)))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(Math.round(vw * scale), 1)
    canvas.height = Math.max(Math.round(vh * scale), 1)

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.fillStyle = '#0F172A'
    ctx.fillRect(0, 0, canvas.width, canvas.height)

    const svgString = serializeSvg(exportSvg)
    const dataUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgString)}`
    const img = new Image()

    await new Promise((resolve, reject) => {
      img.onload = resolve
      img.onerror = reject
      img.src = dataUrl
    })

    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)

    const pngBlob = await new Promise(resolve => {
      canvas.toBlob(resolve, 'image/png')
    })

    if (pngBlob) {
      triggerDownload(pngBlob, `${getSafeFilename()} - 思维导图.png`)
    }
  } catch (e) {
    console.warn('PNG 导出失败:', e)
  } finally {
    cleanupExportStage(stage)
  }
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// ──── 字幕格式转换 ────
function pad2(n) { return String(n).padStart(2, '0') }
function pad3(n) { return String(Math.round(n)).padStart(3, '0') }

function formatTimeSRT(ms) {
  const h = Math.floor(ms / 3600000)
  const m = Math.floor((ms % 3600000) / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  const millis = ms % 1000
  return `${pad2(h)}:${pad2(m)}:${pad2(s)},${pad3(millis)}`
}

function formatTimeVTT(ms) {
  const h = Math.floor(ms / 3600000)
  const m = Math.floor((ms % 3600000) / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  const millis = ms % 1000
  return `${pad2(h)}:${pad2(m)}:${pad2(s)}.${pad3(millis)}`
}

function segmentsToSRT(segments) {
  return segments.map((seg, i) => {
    const start = formatTimeSRT((seg.start || 0) * 1000)
    const end = formatTimeSRT((seg.end || 0) * 1000)
    return `${i + 1}\n${start} --> ${end}\n${seg.text}`
  }).join('\n\n')
}

function segmentsToVTT(segments) {
  const lines = ['WEBVTT', '']
  for (const seg of segments) {
    const start = formatTimeVTT((seg.start || 0) * 1000)
    const end = formatTimeVTT((seg.end || 0) * 1000)
    lines.push(`${start} --> ${end}`)
    lines.push(seg.text)
    lines.push('')
  }
  return lines.join('\n')
}

function segmentsToTXT(segments) {
  return segments.map(s => s.text).join('\n\n')
}

const subtitleFormat = ref('srt')

function downloadSubtitle() {
  let segments = props.subtitleInfo?.segments
  // 如果没有 segments（从缓存加载），从文本生成
  if (!segments || !segments.length) {
    if (!props.subtitleText) return
    const lines = props.subtitleText.split('\n').map(l => l.trim()).filter(l => l.length > 0)
    let curTime = 0
    segments = lines.map(l => {
      // 尝试解析内嵌时间戳 [MM:SS]
      const m = l.match(/^\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*(.*)/)
      if (m) {
        const parts = m[1].split(':').map(Number)
        const sec = parts.length === 3 ? parts[0]*3600 + parts[1]*60 + parts[2] : parts[0]*60 + parts[1]
        curTime = sec
        return { start: sec, end: sec + 3, text: m[2] }
      }
      // 无时间戳，按每句约 4 秒估算
      const start = curTime
      curTime += 4
      return { start, end: curTime, text: l }
    })
  }
  if (!segments.length) return
  let content, ext, mime
  const fmt = subtitleFormat.value
  if (fmt === 'vtt') {
    content = segmentsToVTT(segments); ext = 'vtt'; mime = 'text/vtt'
  } else if (fmt === 'txt') {
    content = segmentsToTXT(segments); ext = 'txt'; mime = 'text/plain'
  } else {
    content = segmentsToSRT(segments); ext = 'srt'; mime = 'text/plain'
  }
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${props.videoTitle || 'subtitle'}.${ext}`
  a.click()
  URL.revokeObjectURL(url)
}

const stageLabels = {
  subtitle_loaded: '字幕加载完成',
  mindmap: '思维导图已生成',
  notes: '笔记已生成',
}

function copyNotes() {
  if (!props.notesMarkdown) return
  const text = props.notesMarkdown
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).catch(() => fallbackCopy(text))
  } else {
    fallbackCopy(text)
  }
}

function fallbackCopy(text) {
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  document.body.appendChild(ta)
  ta.select()
  try { document.execCommand('copy') } catch {}
  document.body.removeChild(ta)
}

function downloadNotes() {
  if (!props.notesMarkdown) return
  const blob = new Blob([props.notesMarkdown], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${props.videoTitle || 'notes'}.md`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="ai-summary">
    <!-- 未开始状态 -->
    <div v-if="!result && !loading && !error" class="summary-trigger">
      <button @click="handleStart" class="summarize-btn">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="summarize-icon">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
        </svg>
        AI 一键总结
      </button>
      <p class="summary-hint">基于视频字幕，AI 自动生成摘要和思维导图</p>
    </div>

    <!-- 错误状态 -->
    <div v-if="error && !loading" class="summary-error" :class="{ 'summary-error-limit': isLimitError }">
      <template v-if="isLimitError">
        <div class="limit-content">
          <div class="limit-header">
            <svg class="limit-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" /></svg>
            <span class="limit-title">今日免费次数已用完</span>
          </div>
          <p class="limit-desc">每日 3 次免费 AI 总结已用尽，升级 Pro 解锁无限次使用</p>
          <button class="pro-btn">升级 Pro</button>
        </div>
      </template>
      <template v-else>
        <svg class="error-icon" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" /></svg>
        <span>{{ error }}</span>
        <button @click="handleRegenerateSummary" class="retry-btn">重试</button>
      </template>
    </div>

    <!-- 结果展示区（含 4 个子 Tab） -->
    <div v-if="result || loading" class="summary-content">
      <!-- 多P分P选择器 -->
      <div v-if="multiParts.length > 1" class="parts-nav">
        <button v-show="canScrollLeft" class="parts-nav-arrow left" @click="scrollParts(-1)">
          <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
        </button>
        <div class="parts-nav-scroll" ref="partsNavScroll" @scroll="updateScrollState">
          <button
            v-for="part in multiParts"
            :key="part.index"
            class="parts-nav-btn"
            :class="{
              active: currentSummarizePart === part.index,
              loading: loading && currentSummarizePart === part.index
            }"
            @click="onSwitchPart && onSwitchPart(part.index)"
            @mouseenter="showTooltip($event, part.title)"
            @mouseleave="hideTooltip"
          >
            <span class="parts-nav-index">P{{ part.index }}</span>
            <span class="parts-nav-title">{{ part.title }}</span>
            <span v-if="loading && currentSummarizePart === part.index" class="parts-nav-spinner"></span>
          </button>
        </div>
        <button v-show="canScrollRight" class="parts-nav-arrow right" @click="scrollParts(1)">
          <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd"/></svg>
        </button>
      </div>
      <!-- 分P标题 tooltip -->
      <Teleport to="body">
        <div v-if="tooltip.visible" class="parts-tooltip" :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }">
          {{ tooltip.text }}
        </div>
      </Teleport>

      <!-- 子 Tab 栏 -->
      <div class="sub-tab-bar">
        <button class="sub-tab-btn" :class="{ active: activeSubTab === 'summary' }" @click="activeSubTab = 'summary'">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="sub-tab-icon"><path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" /></svg>
          摘要
        </button>
        <button class="sub-tab-btn" :class="{ active: activeSubTab === 'subtitle' }" @click="handleTabSubtitle">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="sub-tab-icon"><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" /></svg>
          字幕
        </button>
        <button
          class="sub-tab-btn"
          :class="{ active: activeSubTab === 'mindmap' }"
          @click="activeSubTab = 'mindmap'"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="sub-tab-icon"><path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" /></svg>
          导图
        </button>
        <button
          class="sub-tab-btn"
          :class="{ active: activeSubTab === 'notes' }"
          @click="activeSubTab = 'notes'"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="sub-tab-icon"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" /></svg>
          笔记
        </button>
        <button
          class="sub-tab-btn"
          :class="{ active: activeSubTab === 'qa' }"
          @click="handleTabQA"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="sub-tab-icon"><path stroke-linecap="round" stroke-linejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" /></svg>
          问答
        </button>
      </div>

      <!-- Tab: 摘要 -->
      <div v-show="activeSubTab === 'summary'" class="sub-tab-panel">
        <div v-if="loading && (!regeneratingMode || regeneratingMode === 'summary') && !streamingText" class="loading-skeleton">
          <div class="skeleton-line skeleton-title"></div>
          <div class="skeleton-line skeleton-long"></div>
          <div class="skeleton-line skeleton-medium"></div>
          <div class="skeleton-line skeleton-long"></div>
          <div class="skeleton-line skeleton-short"></div>
        </div>
        <div v-else class="summary-scroll">
          <div class="summary-section">
            <div class="summary-text prose prose-invert prose-sm max-w-none" v-html="renderMarkdown(streamingText || result.summary)"></div>
          </div>
          <div v-if="isPartialSummary && !loading" class="partial-banner">
            <svg viewBox="0 0 20 20" fill="currentColor" class="partial-icon"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/></svg>
            <span>基于视频前段内容的初步摘要，完整分析进行中...</span>
          </div>
          <!-- 学习闪卡 -->
          <div v-if="flashcards && flashcards.length" class="flashcards-section">
            <h4 class="flashcards-title">学习闪卡（{{ flashcards.length }} 张）</h4>
            <div class="flashcards-grid">
              <div v-for="(card, i) in flashcards" :key="i" class="flashcard-item">
                <div class="flashcard-question">
                  <span class="flashcard-label">Q{{ i + 1 }}</span>
                  {{ card.question }}
                </div>
                <div class="flashcard-answer">
                  <span class="flashcard-label">A</span>
                  {{ card.answer }}
                </div>
              </div>
            </div>
          </div>
          <button v-if="!loading" @click="handleRegenerateSummary" class="regenerate-btn">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="regenerate-icon"><path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" /></svg>
            重新生成摘要
          </button>
        </div>
      </div>

      <!-- Tab: 字幕 -->
      <div v-show="activeSubTab === 'subtitle'" class="sub-tab-panel">
        <div v-if="subtitleError" class="subtitle-error-msg">{{ subtitleError }}</div>
        <div v-else-if="subtitleText">
          <div class="subtitle-toolbar">
            <button
              v-if="subtitleSource === 'whisper'"
              @click="handleRegenerateSubtitle"
              :disabled="loading"
              class="subtitle-download-btn"
              title="重新语音识别"
            >
              <svg viewBox="0 0 20 20" fill="currentColor" class="download-icon"><path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd"/></svg>
              重新识别
            </button>
            <div class="subtitle-download-dropdown" ref="downloadDropdownRef">
              <button
                class="subtitle-download-btn"
                :disabled="!hasSubtitleSegments"
                :title="!hasSubtitleSegments ? '该字幕无分段数据，仅支持在线查看' : '下载字幕文件'"
                @click="toggleDownloadMenu"
              >
                <svg viewBox="0 0 20 20" fill="currentColor" class="download-icon"><path d="M10.75 2.75a.75.75 0 00-1.5 0v8.614L6.295 8.235a.75.75 0 10-1.09 1.03l4.25 4.5a.75.75 0 001.09 0l4.25-4.5a.75.75 0 00-1.09-1.03l-2.955 3.129V2.75z"/><path d="M3.5 12.75a.75.75 0 00-1.5 0v2.5A2.75 2.75 0 004.75 18h10.5A2.75 2.75 0 0018 15.25v-2.5a.75.75 0 00-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5z"/></svg>
                下载
                <svg viewBox="0 0 20 20" fill="currentColor" class="dropdown-arrow"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>
              </button>
              <div v-if="showDownloadMenu" class="download-menu">
                <button @click="downloadSubtitleFormat('srt')" class="download-menu-item">SRT 字幕</button>
                <button @click="downloadSubtitleFormat('vtt')" class="download-menu-item">VTT 字幕</button>
                <button @click="downloadSubtitleFormat('txt')" class="download-menu-item">纯文本 TXT</button>
              </div>
            </div>
          </div>
          <div class="subtitle-text-wrapper" ref="subtitleWrapperRef">
            <div class="subtitle-segments">
              <div v-for="(seg, i) in subtitleSegments" :key="i" class="subtitle-segment" :class="{ active: isActiveSegment(seg) }">
                <span v-if="seg.time" class="subtitle-time" :class="{ clickable: seg.seconds != null, active: isActiveSegment(seg) }" @click="seg.seconds != null && onSeekVideo?.(seg.seconds)">{{ seg.time }}</span>
                <span class="subtitle-line">{{ seg.text }}</span>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="subtitle-empty">
          <p class="subtitle-empty-text">该视频无可用的字幕文本</p>
          <p class="subtitle-empty-hint">部分视频仅含弹幕（非转录文本），无法用于 AI 总结或展示</p>
        </div>
      </div>

      <!-- Tab: 思维导图 -->
      <div v-show="activeSubTab === 'mindmap'" class="sub-tab-panel">
        <div v-if="hasMindmap">
          <div class="mindmap-controls">
            <button @click="downloadSVG" class="zoom-btn" title="下载 SVG">
              <svg viewBox="0 0 20 20" fill="currentColor" class="toolbar-icon"><path fill-rule="evenodd" d="M6 2a2 2 0 00-2 2v12a2 2 0 002 2h8a2 2 0 002-2V7.414A2 2 0 0015.414 6L13 3.586A2 2 0 0011.586 3H6zm5 13a1 1 0 102 0V8.414l2.293 2.293a1 1 0 001.414-1.414l-4-4a1 1 0 00-1.414 0l-4 4a1 1 0 001.414 1.414L11 8.414V15z" clip-rule="evenodd"/></svg>
              SVG
            </button>
            <button @click="downloadPNG" class="zoom-btn" title="下载 PNG">
              <svg viewBox="0 0 20 20" fill="currentColor" class="toolbar-icon"><path fill-rule="evenodd" d="M4 3a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V5a2 2 0 00-2-2H4zm12 12H4l4-8 3 6 2-4 3 6z" clip-rule="evenodd"/></svg>
              PNG
            </button>
            <button @click="toggleFullscreen" class="zoom-btn" :title="isFullscreen ? '退出全屏' : '全屏展示'">
              <svg v-if="!isFullscreen" viewBox="0 0 20 20" fill="currentColor" class="toolbar-icon"><path d="M3 4a1 1 0 011-1h4a1 1 0 010 2H6.414l3.293 3.293a1 1 0 01-1.414 1.414L5 6.414V8a1 1 0 01-2 0V4zm9 1a1 1 0 010-2h4a1 1 0 011 1v4a1 1 0 01-2 0V6.414l-3.293 3.293a1 1 0 11-1.414-1.414L13.586 5H12zm-9 7a1 1 0 012 0v1.586l3.293-3.293a1 1 0 011.414 1.414L6.414 15H8a1 1 0 010 2H4a1 1 0 01-1-1v-4zm13-1a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 010-2h1.586l-3.293-3.293a1 1 0 011.414-1.414L15 13.586V12a1 1 0 011-1z"/></svg>
              <svg v-else viewBox="0 0 20 20" fill="currentColor" class="toolbar-icon"><path d="M6 18L18 6M6 6l12 12" stroke="currentColor" stroke-width="2"/></svg>
              {{ isFullscreen ? '退出' : '全屏' }}
            </button>
            <button @click="handleRegenerateMindmap" :disabled="loading" class="zoom-btn" title="重新生成思维导图">
              <svg viewBox="0 0 20 20" fill="currentColor" class="toolbar-icon"><path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd"/></svg>
            </button>
          </div>
          <div ref="mindmapContainer" class="mindmap-container" :class="{ 'mindmap-fullscreen': isFullscreen }">
            <svg ref="mindmapSvg" class="mindmap-svg" :style="isFullscreen ? 'height: 100%' : 'min-height: 500px'"></svg>
          </div>
        </div>
        <div v-else-if="loading" class="mindmap-loading">
          <div class="skeleton-line skeleton-long"></div>
          <div class="skeleton-line skeleton-medium"></div>
          <p class="loading-text">正在生成思维导图...</p>
        </div>
        <div v-else class="mindmap-empty">
          <p>思维导图将在总结完成后自动生成</p>
          <p class="mindmap-empty-hint">请先在"摘要"标签页生成 AI 总结</p>
        </div>
      </div>

      <!-- Tab: 学习笔记 -->
      <div v-show="activeSubTab === 'notes'" class="sub-tab-panel">
        <div v-if="!notesMarkdown && loading" class="notes-loading">
          <div class="skeleton-line skeleton-long"></div>
          <div class="skeleton-line skeleton-medium"></div>
          <p class="loading-text">正在生成学习笔记...</p>
        </div>
        <div v-else-if="notesMarkdown" class="notes-section">
          <div class="notes-toolbar">
            <span v-if="loading" class="notes-streaming-badge">生成中...</span>
            <button @click="copyNotes" class="notes-action-btn">
              <svg viewBox="0 0 20 20" fill="currentColor" class="toolbar-icon"><path d="M8 3a1 1 0 011-1h2a1 1 0 110 2H9a1 1 0 01-1-1z"/><path d="M6 3a2 2 0 00-2 2v11a2 2 0 002 2h8a2 2 0 002-2V5a2 2 0 00-2-2 3 3 0 01-3 3H9a3 3 0 01-3-3z"/></svg>
              复制
            </button>
            <button @click="downloadNotes" class="notes-action-btn">
              <svg viewBox="0 0 20 20" fill="currentColor" class="toolbar-icon"><path d="M10.75 2.75a.75.75 0 00-1.5 0v8.614L6.295 8.235a.75.75 0 10-1.09 1.03l4.25 4.5a.75.75 0 001.09 0l4.25-4.5a.75.75 0 00-1.09-1.03l-2.955 3.129V2.75z"/><path d="M3.5 12.75a.75.75 0 00-1.5 0v2.5A2.75 2.75 0 004.75 18h10.5A2.75 2.75 0 0018 15.25v-2.5a.75.75 0 00-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5z"/></svg>
              下载 .md
            </button>
            <button @click="handleRegenerateNotes" :disabled="loading" class="notes-action-btn" title="重新生成笔记">
              <svg viewBox="0 0 20 20" fill="currentColor" class="toolbar-icon"><path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd"/></svg>
            </button>
          </div>
          <div class="notes-content prose prose-invert prose-sm max-w-none" v-html="renderNotesMarkdown(notesMarkdown)" @click="onNotesClick"></div>
        </div>
        <div v-else class="notes-empty">笔记将在总结完成后自动生成</div>
      </div>

      <!-- Tab: 问答 -->
      <div v-show="activeSubTab === 'qa'" class="sub-tab-panel">
        <div class="chat-container">
          <div v-if="!subtitleText && !isFetchingSubtitle" class="chat-need-subtitle">
            <p>请先加载字幕文本以使用问答功能</p>
            <button @click="onFetchSubtitle" class="fetch-subtitle-btn">加载字幕</button>
          </div>
          <template v-else>
            <div class="chat-messages" ref="chatMessagesEl">
              <div v-if="chatMessages.length === 0" class="chat-empty">
                基于视频字幕内容的 AI 问答，请输入你的问题
              </div>
              <div v-for="(msg, i) in chatMessages" :key="i" class="chat-message" :class="'chat-msg-' + msg.role">
                <span class="chat-role">{{ msg.role === 'user' ? '你' : 'AI' }}</span>
                <div class="chat-content prose prose-invert prose-sm max-w-none" v-html="renderMarkdown(msg.content)"></div>
              </div>
              <div v-if="chatError" class="chat-error">{{ chatError }}</div>
            </div>
            <div class="chat-input-row">
              <textarea
                v-model="chatInput"
                class="chat-input"
                placeholder="基于视频字幕提问..."
                rows="2"
                :disabled="isChatStreaming"
                @keydown.enter.exact.prevent="sendChat"
              ></textarea>
              <button @click="sendChat" :disabled="isChatStreaming || !chatInput.trim()" class="chat-send-btn">
                <svg v-if="!isChatStreaming" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="send-icon"><path stroke-linecap="round" stroke-linejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" /></svg>
                <svg v-else class="send-icon spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" /></svg>
              </button>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ai-summary { padding: 0; }

/* 触发按钮 */
.summary-trigger { display: flex; flex-direction: column; align-items: center; gap: 0.75rem; padding: 2rem 1rem; }
.summarize-btn { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.75rem 1.5rem; background: linear-gradient(135deg, rgba(139, 92, 246, 0.2) 0%, rgba(59, 130, 246, 0.2) 100%); border: 1px solid rgba(139, 92, 246, 0.3); border-radius: 10px; color: #C4B5FD; font-size: 0.9375rem; font-weight: 600; cursor: pointer; transition: all 0.2s; }
.summarize-btn:hover { background: linear-gradient(135deg, rgba(139, 92, 246, 0.3) 0%, rgba(59, 130, 246, 0.3) 100%); border-color: rgba(139, 92, 246, 0.5); transform: translateY(-1px); }
.summarize-icon { width: 20px; height: 20px; }
.summary-hint { font-size: 0.8125rem; color: var(--text-muted); text-align: center; }

/* 加载 */
.summary-loading { padding: 1.5rem; display: flex; flex-direction: column; gap: 0.75rem; }
.loading-skeleton { display: flex; flex-direction: column; gap: 0.75rem; }
.skeleton-line { height: 16px; background: linear-gradient(90deg, rgba(255,255,255,0.05) 25%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 75%); background-size: 200% 100%; animation: skeleton-shimmer 1.5s infinite; border-radius: 4px; }
.skeleton-title { width: 40%; height: 20px; }
.skeleton-long { width: 100%; }
.skeleton-medium { width: 75%; }
.skeleton-short { width: 50%; }
@keyframes skeleton-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
.loading-text { font-size: 0.8125rem; color: var(--text-muted); text-align: center; margin-top: 0.5rem; }

.streaming-indicator { display: inline-flex; align-items: center; gap: 0.375rem; font-size: 0.8125rem; color: var(--text-muted); margin-top: 0.5rem; }
.streaming-indicator::before { content: ''; width: 6px; height: 6px; background: var(--accent-blue); border-radius: 50%; animation: pulse-dot 1s infinite; }
@keyframes pulse-dot { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

/* 初步摘要横幅 */
.partial-banner {
  display: flex; align-items: center; gap: 0.5rem;
  margin-top: 0.75rem; padding: 0.5rem 0.75rem;
  background: rgba(251, 191, 36, 0.08);
  border: 1px solid rgba(251, 191, 36, 0.15);
  border-radius: 8px;
  font-size: 0.75rem; color: #FCD34D;
}
.partial-icon { width: 16px; height: 16px; flex-shrink: 0; }

/* 流式文本 */
.streaming-text { min-height: 60px; padding: 0.75rem 1rem; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,0.02); }
.streaming-text :deep(pre) { background: rgba(0,0,0,0.3); padding: 0.75rem 1rem; border-radius: 6px; overflow-x: auto; }
.streaming-text :deep(blockquote) { border-left-color: var(--accent-blue); }
.streaming-text :deep(a) { color: var(--accent-blue); }

/* 子 Tab 栏 */
/* 多P分P选择器 */
.parts-nav { margin-bottom: 1rem; position: relative; display: flex; align-items: center; }
.parts-nav-scroll { display: flex; gap: 0.5rem; overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.1) transparent; padding: 0.25rem 0; flex: 1; min-width: 0; }
.parts-nav-scroll::-webkit-scrollbar { height: 4px; }
.parts-nav-scroll::-webkit-scrollbar-track { background: transparent; }
.parts-nav-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
.parts-nav-arrow { flex-shrink: 0; width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; background: rgba(255,255,255,0.06); border: 1px solid var(--border); border-radius: 6px; color: var(--text-muted); cursor: pointer; transition: all 0.15s; padding: 0; }
.parts-nav-arrow:hover { background: rgba(255,255,255,0.12); color: var(--text-secondary); }
.parts-nav-arrow svg { width: 14px; height: 14px; }
.parts-nav-arrow.left { margin-right: 0.25rem; }
.parts-nav-arrow.right { margin-left: 0.25rem; }
.parts-nav-btn { display: inline-flex; align-items: center; gap: 0.375rem; padding: 0.4rem 0.75rem; background: rgba(255,255,255,0.04); border: 1px solid var(--border); border-radius: 8px; color: var(--text-muted); font-size: 0.8125rem; cursor: pointer; transition: all 0.2s; white-space: nowrap; flex-shrink: 0; }
.parts-nav-btn:hover { background: rgba(255,255,255,0.08); color: var(--text-secondary); border-color: rgba(255,255,255,0.12); }
.parts-nav-btn.active { background: rgba(99,102,241,0.12); border-color: rgba(99,102,241,0.4); color: var(--accent-blue, #818CF8); }
.parts-nav-btn.loading { pointer-events: none; opacity: 0.8; }
.parts-nav-index { font-weight: 600; font-size: 0.75rem; color: var(--accent-blue, #818CF8); opacity: 0.8; }
.parts-nav-btn.active .parts-nav-index { opacity: 1; }
.parts-nav-title { }
.parts-nav-spinner { width: 12px; height: 12px; border: 2px solid rgba(99,102,241,0.3); border-top-color: var(--accent-blue, #818CF8); border-radius: 50%; animation: spin 0.8s linear infinite; flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }
.parts-tooltip { position: fixed; transform: translateX(-50%) translateY(-100%); padding: 0.375rem 0.75rem; background: rgba(15,23,42,0.95); color: #e2e8f0; font-size: 0.75rem; border-radius: 6px; pointer-events: none; z-index: 9999; max-width: 400px; white-space: normal; word-break: break-all; line-height: 1.4; box-shadow: 0 4px 12px rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); }

.sub-tab-bar { display: flex; gap: 0; border-bottom: 1px solid var(--border); margin-bottom: 1.25rem; overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none; }
.sub-tab-bar::-webkit-scrollbar { display: none; }
.sub-tab-btn { padding: 0.625rem 0.75rem; background: transparent; border: none; border-bottom: 2px solid transparent; color: var(--text-muted); font-size: 0.8125rem; font-weight: 500; cursor: pointer; transition: all 0.15s; display: inline-flex; align-items: center; gap: 0.3rem; white-space: nowrap; flex-shrink: 0; }
.sub-tab-btn:hover { color: var(--text-secondary); }
.sub-tab-btn.active { color: var(--accent-blue); border-bottom-color: var(--accent-blue); }
.sub-tab-icon { width: 14px; height: 14px; flex-shrink: 0; }

.sub-tab-panel { min-height: 100px; }

/* 统一可滚动内容面板 */
.summary-scroll {
  max-height: 500px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(255,255,255,0.12) transparent;
  padding-right: 0.25rem;
}
.summary-scroll::-webkit-scrollbar { width: 6px; }
.summary-scroll::-webkit-scrollbar-track { background: transparent; }
.summary-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 3px; }

/* 摘要 */
.summary-section { padding: 0; margin-bottom: 1.25rem; }
.summary-text { margin: 0; }
.summary-text :deep(pre) { background: rgba(0,0,0,0.3); padding: 0.75rem 1rem; border-radius: 6px; overflow-x: auto; }
.summary-text :deep(blockquote) { border-left-color: var(--accent-blue); }
.summary-text :deep(a) { color: var(--accent-blue); }
.summary-text :deep(ul),
.summary-text :deep(ol),
.chat-content :deep(ul),
.chat-content :deep(ol) {
  margin: 0.75rem 0;
  padding-inline-start: 1.5rem;
}
.summary-text :deep(ul),
.chat-content :deep(ul) {
  list-style-type: disc;
}
.summary-text :deep(ol),
.chat-content :deep(ol) {
  list-style-type: decimal;
}
.summary-text :deep(li),
.chat-content :deep(li) {
  margin: 0.35rem 0;
  padding-left: 0.2rem;
}
.summary-text :deep(ul ul),
.summary-text :deep(ol ol),
.summary-text :deep(ul ol),
.summary-text :deep(ol ul),
.chat-content :deep(ul ul),
.chat-content :deep(ol ol),
.chat-content :deep(ul ol),
.chat-content :deep(ol ul) {
  margin: 0.35rem 0 0;
}

/* 字幕展示 */
.subtitle-toolbar { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; }
.subtitle-download-btn { display: inline-flex; align-items: center; gap: 0.375rem; padding: 0.375rem 0.75rem; background: rgba(59, 130, 246, 0.12); border: 1px solid rgba(59, 130, 246, 0.25); border-radius: 6px; color: #93C5FD; font-size: 0.8125rem; font-weight: 500; cursor: pointer; transition: all 0.15s; }
.subtitle-download-btn:hover:not(:disabled) { background: rgba(59, 130, 246, 0.2); border-color: rgba(59, 130, 246, 0.4); }
.subtitle-download-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.download-icon { width: 14px; height: 14px; }
.dropdown-arrow { width: 14px; height: 14px; margin-left: 0.25rem; }
.subtitle-download-dropdown { position: relative; display: inline-block; }
.download-menu {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  background: rgba(30, 32, 48, 0.98);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 4px;
  min-width: max-content;
  z-index: 10;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(8px);
}
.download-menu-item {
  display: block;
  width: 100%;
  padding: 8px 12px;
  text-align: left;
  font-size: 0.8125rem;
  color: var(--text-secondary);
  background: none;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  white-space: nowrap;
}
.download-menu-item:hover { background: rgba(255, 255, 255, 0.08); }
.subtitle-text-wrapper {
  max-height: 500px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.75rem;
  background: rgba(0, 0, 0, 0.15);
  scrollbar-width: thin;
  scrollbar-color: rgba(255,255,255,0.12) transparent;
}
.subtitle-text-wrapper::-webkit-scrollbar { width: 6px; }
.subtitle-text-wrapper::-webkit-scrollbar-track { background: transparent; }
.subtitle-text-wrapper::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 3px; }
.subtitle-text-wrapper::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.2); }
.subtitle-segments { display: flex; flex-direction: column; gap: 0.5rem; }
.subtitle-segment {
  display: flex;
  gap: 0.75rem;
  padding: 0.375rem 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  line-height: 1.6;
}
.subtitle-time {
  flex-shrink: 0;
  width: 3.5rem;
  font-size: 0.75rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.subtitle-time.clickable {
  cursor: pointer;
  color: #93C5FD;
}
.subtitle-time.clickable:hover {
  color: #BFDBFE;
}
.subtitle-time.active {
  color: #60A5FA;
  font-weight: 600;
}
.subtitle-segment.active {
  background: rgba(59, 130, 246, 0.08);
  border-radius: 4px;
}
.subtitle-line {
  flex: 1;
  font-size: 0.875rem;
  color: var(--text-secondary);
}
.subtitle-empty { padding: 2rem; text-align: center; }
.subtitle-empty-text { font-size: 0.9375rem; color: var(--text-secondary); margin: 0 0 0.5rem 0; }
.subtitle-empty-hint { font-size: 0.8125rem; color: var(--text-muted); margin: 0; }
.subtitle-loading { display: flex; flex-direction: column; gap: 0.5rem; padding: 1rem; }
.subtitle-error-msg { color: #FCA5A5; padding: 1rem; font-size: 0.875rem; }
.fetch-subtitle-btn { padding: 0.5rem 1.25rem; background: rgba(59, 130, 246, 0.15); border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 8px; color: #93C5FD; font-size: 0.875rem; cursor: pointer; }

/* 思维导图 */
.mindmap-controls { display: flex; align-items: center; justify-content: flex-end; gap: 0.375rem; margin-bottom: 0.75rem; flex-wrap: wrap; }
.zoom-btn {
  display: inline-flex; align-items: center; gap: 0.25rem;
  height: 30px; padding: 0 0.625rem;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 7px;
  color: var(--text-secondary);
  font-size: 0.75rem; font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}
.zoom-btn:hover { background: rgba(255,255,255,0.08); border-color: rgba(255,255,255,0.18); color: var(--text-primary); }
.toolbar-icon { width: 14px; height: 14px; }
.mindmap-container {
  overflow: hidden;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 10px;
  background: #0F172A;
}
.mindmap-svg { display: block; width: 100%; min-height: 500px; }
.mindmap-empty { padding: 2rem; text-align: center; color: var(--text-muted); }
.mindmap-empty-hint { font-size: 0.8rem; color: var(--text-muted); margin-top: 0.25rem; }
.mindmap-loading { display: flex; flex-direction: column; align-items: center; gap: 0.75rem; padding: 2rem; }
.mindmap-loading .loading-text { font-size: 0.8125rem; color: var(--text-muted); margin: 0; }

/* markmap 自定义样式 */
.mindmap-container :deep(.markmap-foreign) { display: inline-block !important; }
.mindmap-container :deep(foreignObject) { overflow: visible !important; }
.mindmap-container :deep(foreignObject div) {
  font-size: 15px !important;
  font-family: 'Noto Sans SC', -apple-system, sans-serif !important;
  color: #F8FAFC !important;
  background: transparent !important;
  padding: 2px 4px !important;
  border-radius: 0 !important;
  line-height: 1.6 !important;
  font-weight: 500 !important;
  text-shadow:
    0 1px 1px rgba(15, 23, 42, 0.95),
    0 0 8px rgba(15, 23, 42, 0.85),
    0 0 16px rgba(15, 23, 42, 0.55) !important;
}

/* 全屏 */
.mindmap-fullscreen {
  position: fixed !important; top: 0; left: 0; right: 0; bottom: 0;
  z-index: 50; border-radius: 0 !important; border: none !important;
  background: #0F172A;
}
.mindmap-container:fullscreen { background: #0F172A; display: flex; align-items: center; justify-content: center; }
.mindmap-container:fullscreen .mindmap-svg { max-width: 100vw; max-height: 100vh; }

/* 问答 */
.chat-container { display: flex; flex-direction: column; height: 400px; }
.chat-need-subtitle { padding: 2rem; text-align: center; color: var(--text-muted); }
.chat-messages { flex: 1; overflow-y: auto; padding: 0.5rem 0; display: flex; flex-direction: column; gap: 0.75rem; }
.chat-empty { text-align: center; color: var(--text-muted); font-size: 0.8125rem; padding: 2rem 1rem; }
.chat-message { padding: 0.625rem 0.875rem; border-radius: 8px; max-width: 90%; }
.chat-msg-user { align-self: flex-end; background: rgba(59, 130, 246, 0.15); border: 1px solid rgba(59, 130, 246, 0.2); }
.chat-msg-assistant { align-self: flex-start; background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border); }
.chat-role { font-size: 0.6875rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.25rem; display: block; }
.chat-content { margin: 0; }
.chat-content :deep(pre) { background: rgba(0,0,0,0.3); padding: 0.5rem 0.75rem; border-radius: 4px; overflow-x: auto; font-size: 0.8125rem; }
.chat-content :deep(blockquote) { border-left-color: var(--accent-blue); }
.chat-content :deep(a) { color: var(--accent-blue); }
.chat-error { color: #FCA5A5; font-size: 0.75rem; padding: 0.25rem 0.5rem; }
.chat-input-row { display: flex; gap: 0.5rem; margin-top: 0.5rem; padding-top: 0.75rem; border-top: 1px solid var(--border); }
.chat-input { flex: 1; padding: 0.625rem 0.75rem; background: rgba(255,255,255,0.05); border: 1px solid var(--border); border-radius: 8px; color: var(--text-primary); font-size: 0.875rem; resize: none; outline: none; font-family: inherit; }
.chat-input:focus { border-color: var(--accent-blue); }
.chat-send-btn { padding: 0.5rem 0.875rem; background: linear-gradient(135deg, var(--accent-blue) 0%, var(--accent-cyan) 100%); border: none; border-radius: 8px; color: white; cursor: pointer; display: flex; align-items: center; }
.chat-send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.send-icon { width: 18px; height: 18px; }
.spinner { animation: spin 1.5s linear infinite; }
@keyframes spin { 100% { transform: rotate(360deg); } }

/* 错误 */
.summary-error { display: flex; align-items: center; gap: 0.75rem; padding: 1rem 1.25rem; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: var(--radius); color: #FCA5A5; font-size: 0.875rem; }
.summary-error .error-icon { width: 18px; height: 18px; flex-shrink: 0; }
.retry-btn { margin-left: auto; padding: 0.25rem 0.75rem; background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px; color: #FCA5A5; font-size: 0.8125rem; cursor: pointer; }
.summary-error-limit { background: linear-gradient(135deg, rgba(139, 92, 246, 0.1) 0%, rgba(59, 130, 246, 0.1) 100%); border-color: rgba(139, 92, 246, 0.25); padding: 1.25rem; }
.limit-content { display: flex; flex-direction: column; gap: 0.75rem; width: 100%; }
.limit-header { display: flex; align-items: center; gap: 0.5rem; }
.limit-icon { width: 20px; height: 20px; color: #FCD34D; }
.limit-title { font-size: 0.9375rem; font-weight: 600; color: var(--text-primary); }
.limit-desc { font-size: 0.8125rem; color: var(--text-muted); margin: 0; }
.pro-btn { display: inline-flex; align-items: center; justify-content: center; gap: 0.375rem; padding: 0.5rem 1.25rem; background: linear-gradient(135deg, #8B5CF6 0%, #3B82F6 100%); border: none; border-radius: 8px; color: white; font-size: 0.875rem; font-weight: 600; cursor: pointer; align-self: flex-start; }
.pro-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3); }

.flashcards-section { margin-top: 1.25rem; padding-top: 1.25rem; border-top: 1px solid var(--border); }
.flashcards-title { font-size: 0.9375rem; font-weight: 600; color: var(--text-primary); margin: 0 0 0.75rem 0; }
.flashcards-grid { display: flex; flex-direction: column; gap: 0.625rem; }
.flashcard-item { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: rgba(255,255,255,0.02); }
.flashcard-question { padding: 0.625rem 0.875rem; font-size: 0.875rem; color: var(--text-primary); display: flex; gap: 0.5rem; align-items: flex-start; border-bottom: 1px solid rgba(255,255,255,0.05); background: rgba(59, 130, 246, 0.05); }
.flashcard-answer { padding: 0.625rem 0.875rem; font-size: 0.8125rem; color: var(--text-secondary); display: flex; gap: 0.5rem; align-items: flex-start; }
.flashcard-label { font-weight: 700; font-size: 0.75rem; color: var(--accent-blue); flex-shrink: 0; min-width: 1.25rem; }

.regenerate-btn { display: inline-flex; align-items: center; gap: 0.375rem; padding: 0.5rem 1rem; background: transparent; border: 1px solid var(--border); border-radius: 8px; color: var(--text-muted); font-size: 0.8125rem; cursor: pointer; margin-top: 0.5rem; }
.regenerate-btn:hover { background: var(--bg-card-hover); border-color: var(--border-hover); color: var(--text-primary); }
.regenerate-icon { width: 16px; height: 16px; }

/* 水平进度条 */
.progress-bar-container {
  margin-bottom: 1.25rem;
  padding: 0.75rem 0.5rem;
}
.progress-steps {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
}
.progress-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  flex-shrink: 0;
}
.step-circle {
  width: 24px; height: 24px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: rgba(255,255,255,0.05);
  border: 2px solid var(--border);
  transition: all 0.3s;
}
.progress-step.done .step-circle {
  background: rgba(34, 197, 94, 0.15);
  border-color: var(--success);
}
.progress-step.active .step-circle {
  background: rgba(59, 130, 246, 0.15);
  border-color: var(--accent-blue);
  box-shadow: 0 0 8px rgba(59, 130, 246, 0.3);
}
.step-check { color: var(--success); font-size: 0.7rem; line-height: 1; }
.step-spinner {
  width: 12px; height: 12px;
  border: 2px solid rgba(255,255,255,0.15);
  border-top-color: var(--accent-blue);
  border-radius: 50%;
  animation: step-spin 0.7s linear infinite;
}
@keyframes step-spin { to { transform: rotate(360deg); } }
.step-label {
  font-size: 0.65rem;
  color: var(--text-muted);
  white-space: nowrap;
  transition: color 0.3s;
}
.progress-step.done .step-label { color: var(--text-secondary); }
.progress-step.active .step-label { color: var(--accent-blue); font-weight: 500; }

.progress-line {
  width: 28px; height: 2px;
  background: var(--border);
  margin: 0 0.25rem;
  margin-bottom: 1.25rem;
  border-radius: 1px;
  transition: background 0.5s;
  flex-shrink: 0;
}
.progress-line.filled {
  background: var(--success);
}
@media (max-width: 768px) {
  .progress-line { width: 18px; }
  .step-label { font-size: 0.6rem; }
}

/* 笔记 */
.notes-section { display: flex; flex-direction: column; gap: 0.75rem; }
.notes-toolbar { display: flex; gap: 0.5rem; align-items: center; justify-content: flex-end; }
.notes-streaming-badge { font-size: 0.75rem; color: var(--accent-cyan); margin-right: auto; animation: pulse-dot 1.5s infinite; }
.notes-action-btn {
  display: inline-flex; align-items: center; gap: 0.375rem;
  padding: 0.375rem 0.75rem;
  background: rgba(255,255,255,0.06);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 0.8125rem; cursor: pointer;
  transition: all 0.15s;
}
.notes-action-btn:hover { background: rgba(255,255,255,0.1); color: var(--text-primary); }
.notes-content {
  max-height: 600px; overflow-y: auto;
  padding: 1.25rem;
  background: linear-gradient(135deg, rgba(15, 23, 42, 0.6) 0%, rgba(30, 41, 59, 0.3) 100%);
  border: 1px solid var(--border);
  border-radius: 10px;
  line-height: 1.8;
}
.notes-content :deep(h1) { font-size: 1.25rem; font-weight: 700; color: var(--text-primary); margin: 1rem 0 0.5rem; padding-bottom: 0.375rem; border-bottom: 1px solid var(--border); }
.notes-content :deep(h2) { font-size: 1.1rem; font-weight: 600; color: #E2E8F0; margin: 0.875rem 0 0.5rem; }
.notes-content :deep(h3) { font-size: 1rem; font-weight: 600; color: #CBD5E1; margin: 0.75rem 0 0.375rem; }
.notes-content :deep(p) { margin: 0.5rem 0; }
.notes-content :deep(ul), .notes-content :deep(ol) { margin: 0.5rem 0; padding-inline-start: 1.5rem; }
.notes-content :deep(li) { margin: 0.25rem 0; }
.notes-content :deep(pre) { background: rgba(0,0,0,0.4); padding: 0.75rem 1rem; border-radius: 6px; overflow-x: auto; margin: 0.75rem 0; }
.notes-content :deep(code) { font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 0.8125rem; }
.notes-content :deep(blockquote) {
  border-left: 3px solid var(--accent-blue);
  padding: 0.375rem 0.75rem; margin: 0.5rem 0;
  background: rgba(59, 130, 246, 0.08);
  border-radius: 0 6px 6px 0;
  color: #93C5FD;
}
.notes-content :deep(strong) { color: #F8FAFC; font-weight: 600; }
.notes-content :deep(a) { color: var(--accent-blue); }
.notes-content :deep(hr) { border-color: var(--border); margin: 1rem 0; }
.notes-content :deep(.notes-timestamp) {
  display: inline-flex;
  align-items: center;
  padding: 0 0.375rem;
  margin: 0 0.125rem;
  background: rgba(59, 130, 246, 0.12);
  border: 1px solid rgba(59, 130, 246, 0.25);
  border-radius: 4px;
  font-size: 0.8125rem;
  font-variant-numeric: tabular-nums;
  color: #93C5FD;
  cursor: pointer;
  transition: background 0.15s;
}
.notes-content :deep(.notes-timestamp:hover) {
  background: rgba(59, 130, 246, 0.25);
}
.notes-loading { display: flex; flex-direction: column; align-items: center; gap: 0.75rem; padding: 2rem; }
.notes-empty { padding: 2rem; text-align: center; color: var(--text-muted); }

@media (max-width: 768px) {
  /* 子 Tab 栏：缩小以放下 5 个 Tab */
  .sub-tab-btn { padding: 0.5rem 0.5rem; font-size: 0.75rem; gap: 0.2rem; }
  .sub-tab-icon { width: 12px; height: 12px; }
  .sub-tab-bar { scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.1) transparent; }
  .sub-tab-bar::-webkit-scrollbar { display: block; height: 3px; }
  .sub-tab-bar::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }

  /* 内容区高度限制 */
  .summary-scroll { max-height: 60vh; }
  .mindmap-container { padding: 0.5rem; }
  .chat-container { height: 50vh; }
  .notes-content { max-height: 50vh; padding: 0.875rem; }

  /* 笔记字体缩小 */
  .notes-content :deep(h1) { font-size: 1.1rem; }
  .notes-content :deep(h2) { font-size: 1rem; }
  .notes-content :deep(h3) { font-size: 0.9375rem; }
  .notes-content :deep(pre) { padding: 0.5rem 0.75rem; font-size: 0.75rem; }

  /* 问答输入 */
  .chat-input-row { gap: 0.375rem; }
  .chat-input { font-size: 0.875rem; padding: 0.625rem 0.75rem; }
  .chat-send-btn { padding: 0.625rem 1rem; font-size: 0.8125rem; }

  /* 闪卡 */
  .flashcard-answer { font-size: 0.8125rem; }

  /* 分P选择器 */
  .parts-nav-btn { padding: 0.375rem 0.625rem; font-size: 0.75rem; max-width: 150px; }
}
</style>
