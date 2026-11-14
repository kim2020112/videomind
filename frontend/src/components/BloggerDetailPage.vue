<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useBloggers } from '../composables/useBloggers.js'
import { thumbnailSrc } from '../utils/thumbnail.js'
import { useAuth } from '../composables/useAuth.js'
import { bloggerContextKey, saveBloggerContext, readBloggerContext } from '../utils/bloggerNavigation.js'
import ContentBadges from './ContentBadges.vue'
import ConfirmDialog from './ConfirmDialog.vue'

const props = defineProps({
  activeTasks: { type: Array, default: () => [] },
})
const emit = defineEmits(['back', 'open-workspace'])

const route = useRoute()
const router = useRouter()
const {
  bloggers, videos, videosTotal, videosLearnedTotal, videosSubtitleTotal, videosMatchedTotal, videosHasMore, videosLoading,
  pages, pagesLoading, batches, currentBatch, batchLoading, pending, error,
  listBloggers, updateBlogger, syncBlogger, cancelSync, listVideos, listPages,
  createBatch, listBatches, getBatch, batchAction,
  startBatchPolling, stopBatchPolling, startSyncPolling,
} = useBloggers()

const subId = computed(() => String(route.params.id || ''))
const blogger = computed(() => bloggers.value.find(item => String(item.id) === subId.value))

const PAGE_SIZE = 20
const searchQuery = ref('')
const subtitleOnly = ref(false)
const restoredVideoId = ref(null)
const missingVideo = ref(null)
const auth = useAuth()
const identityKey = computed(() => auth.user?.value?.id ? `user:${auth.user.value.id}` : `guest:${auth.guestId?.value || 'local'}`)
let disposed = false
let loadEpoch = 0
const learnedFilter = ref('all') // all | learned | unlearned
const selectionMode = ref(false)
const selected = ref(new Set())
const expandedVideoId = ref(null)
const batchMode = ref('full')
const editingAlias = ref(false)
const aliasValue = ref('')
const toast = ref(null)
let toastTimer = null
let restoreTimer = null

function showToast(message, type = 'error') {
  toast.value = { message, type }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = null }, 4500)
}

const confirmation = ref(null)
let confirmationResolve = null
function requestConfirmation(message, title = '确认操作') {
  confirmation.value = { message, title }
  return new Promise(resolve => { confirmationResolve = resolve })
}
function closeConfirmation(confirmed = false) {
  confirmation.value = null
  confirmationResolve?.(confirmed)
  confirmationResolve = null
}

function displayNameOf(item) {
  return item?.alias || item?.name || `UP ${item?.uid || ''}`
}

function formatDuration(seconds) {
  const s = Number(seconds) || 0
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function formatDate(ts) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleDateString()
}

function statusLabel(item) {
  switch (item.status) {
    case 'queued': return '排队中'
    case 'running': return phaseLabel(item.phase)
    case 'done': return item.phase === 'reused' ? '已整理过 · 复用缓存' : '完成'
    case 'failed': return item.error ? `失败 · ${item.error}` : '失败'
    case 'skipped': return item.error_code === 'usage_limit' ? '额度已用完 · 跳过' : '已跳过'
    case 'cancelled': return '已取消'
    case 'paused': return '已暂停'
    default: return item.status
  }
}

function phaseLabel(phase) {
  switch (phase) {
    case 'meta': return '解析中'
    case 'subtitle': return '获取字幕'
    case 'whisper': return '转录中'
    case 'ai': return '生成学习资料'
    case 'reused': return '复用缓存'
    default: return '处理中'
  }
}

function batchStatusLabel(status) {
  switch (status) {
    case 'queued': return '排队中'
    case 'running': return '进行中'
    case 'done': return '全部完成'
    case 'failed': return '部分失败'
    case 'cancelled': return '已取消'
    case 'paused': return '已暂停'
    default: return status
  }
}

function toneFor(status) {
  if (status === 'done') return 'tone-ok'
  if (status === 'failed' || status === 'skipped' || status === 'cancelled') return 'tone-bad'
  return 'tone-busy'
}

function syncLabel() {
  const item = blogger.value
  if (!item) return ''
  switch (item.sync_status) {
    case 'running': return item.sync_mode === 'deep' ? '深度同步中…' : '增量同步中…'
    case 'queued': return '同步排队中'
    case 'complete': return item.last_synced_at ? `目录已同步 · ${item.catalog_count ?? 0} 个投稿` : '目录已同步'
    case 'paused': return item.sync_error_code === 'login' ? '需配置 B 站 Cookie（backend/.env 的 BILIBILI_COOKIE）' : '同步已暂停'
    case 'failed': return item.sync_error ? `同步失败 · ${item.sync_error}` : '同步失败'
    case 'interrupted': return '同步被中断，可点「同步」续跑'
    case 'cancelled': return '同步已取消'
    default: return '尚未同步'
  }
}

function syncProgressText() {
  const item = blogger.value
  if (!item) return ''
  const page = item.sync_page || 0
  const found = item.sync_found || 0
  const added = item.sync_added || 0
  const expected = item.sync_expected
  const scanned = item.sync_mode === 'deep' && expected ? `${found}/${expected}` : `${found}`
  return `第 ${page} 页 · 已扫描 ${scanned} · 新增 ${added}`
}

function isSyncActive() {
  const item = blogger.value
  return !!item && (item.sync_status === 'running' || item.sync_status === 'queued')
}

function taskForItem(item) {
  return props.activeTasks.find(task => task.url_hash === item.url_hash)
}

// ── 查询条件 ↔ URL 同步 ──
function syncRouteQuery() {
  const query = {}
  if (searchQuery.value) query.q = searchQuery.value
  if (subtitleOnly.value) query.has_subtitle = '1'
  if (learnedFilter.value !== 'all') query.learned = learnedFilter.value
  const page = Math.max(1, Math.ceil(videos.value.length / PAGE_SIZE))
  if (page > 1) query.page = String(page)
  router.replace({ name: 'blogger-detail', params: { id: subId.value }, query })
}

function currentQueryState() {
  return {
    q: typeof route.query.q === 'string' ? route.query.q : '',
    learned: ['learned', 'unlearned'].includes(route.query.learned) ? route.query.learned : 'all',
    subtitle: route.query.has_subtitle === '1',
  }
}

async function refreshVideos({ append = false, anchorId } = {}) {
  return await listVideos(subId.value, {
    q: searchQuery.value,
    learned: learnedFilter.value,
    has_subtitle: subtitleOnly.value ? '1' : undefined,
    anchor_id: anchorId,
    limit: PAGE_SIZE,
    offset: append ? videos.value.length : 0,
  }, { append })
}

async function handleSearch() {
  expandedVideoId.value = null
  missingVideo.value = null
  await refreshVideos()
  syncRouteQuery()
}

async function setLearnedFilter(value) {
  if (learnedFilter.value === value) return
  learnedFilter.value = value
  expandedVideoId.value = null
  missingVideo.value = null
  await refreshVideos()
  syncRouteQuery()
}

async function loadMore() {
  await refreshVideos({ append: true })
  syncRouteQuery()
}

async function toggleSubtitleOnly() {
  expandedVideoId.value = null
  missingVideo.value = null
  await refreshVideos()
  syncRouteQuery()
}

// ── alias ──
function startEditAlias() {
  aliasValue.value = blogger.value?.alias || ''
  editingAlias.value = true
}

async function saveAlias() {
  const value = aliasValue.value.trim()
  editingAlias.value = false
  if (value === (blogger.value?.alias || '')) return
  try {
    await updateBlogger(Number(subId.value), { alias: value })
    await listBloggers()
    showToast(value ? '备注已保存' : '备注已清除', 'success')
  } catch (err) {
    showToast(error.value || err.message)
  }
}

// ── 同步 ──
async function handleSync(mode = 'incremental') {
  try {
    const result = await syncBlogger(Number(subId.value), { mode })
    await listBloggers()
    showToast(result.already_running ? '同步已在进行中' : (mode === 'deep' ? '已开始深度同步' : '已开始增量同步'), 'success')
    ensureSyncPolling()
  } catch (err) {
    showToast(error.value || err.message)
  }
}

async function handleDeepSync() {
  if (!await requestConfirmation(
    '将重新扫描该博主的全部投稿页，耗时较长；用于补漏或刷新旧投稿信息。日常更新用「同步」即可。',
    '深度同步',
  )) return
  await handleSync('deep')
}

async function handleCancelSync() {
  try {
    await cancelSync(Number(subId.value))
    await listBloggers()
    showToast('已请求取消同步', 'success')
  } catch (err) {
    showToast(error.value || err.message)
  }
}

function ensureSyncPolling() {
  startSyncPolling(isSyncActive, listBloggers)
}

// ── 多选/批量 ──
function toggleSelectAll() {
  if (selected.value.size === videos.value.length && videos.value.length > 0) {
    selected.value = new Set()
    return
  }
  selected.value = new Set(videos.value.map(item => item.id))
}

function toggleSelect(id) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

async function toggleExpand(video) {
  if (expandedVideoId.value === video.id) {
    expandedVideoId.value = null
    return
  }
  expandedVideoId.value = video.id
  await listPages(subId.value, video.id)
}

async function handleCreateBatch() {
  const videoIds = [...selected.value]
  if (!videoIds.length) return showToast('请先勾选要处理的投稿')
  if (!await requestConfirmation(
    `将为 ${videoIds.length} 个投稿批量生成学习资料（摘要/笔记/思维导图/问答），已整理过的内容会自动跳过。继续？`,
    '批量生成',
  )) return
  try {
    const batch = await createBatch(subId.value, {
      selection: { video_ids: videoIds, include_all_parts: true },
      mode: batchMode.value,
    })
    selectionMode.value = false
    selected.value = new Set()
    if (batch?.usage && !batch.usage.allowed) {
      showToast('今日 AI 额度已用完，批次会在生成前暂停')
    } else {
      showToast(`批次已创建，共 ${batch.total} 个分 P`, 'success')
    }
    await listBatches(subId.value)
    if (batch?.id) {
      await getBatch(batch.id)
      startBatchPolling(batch.id, () => listBatches(subId.value))
    }
  } catch (err) {
    showToast(error.value || err.message)
  }
}

async function handleBatchAction(action) {
  if (!currentBatch.value) return
  const labels = { cancel: '取消', pause: '暂停', resume: '恢复', retry_failed: '重试失败条目' }
  if (action === 'cancel' && !await requestConfirmation('确定取消该批次？未开始的条目将不再处理。', '取消批次')) return
  try {
    await batchAction(currentBatch.value.id, action)
    await Promise.all([getBatch(currentBatch.value.id), listBatches(subId.value)])
    showToast(`${labels[action]}成功`, 'success')
  } catch (err) {
    showToast(error.value || err.message || `${labels[action]}失败`)
  }
}

async function openBatch(batch) {
  await getBatch(batch.id)
  startBatchPolling(batch.id, () => getBatch(batch.id))
}

async function openWorkspace(item, videoId = item.id) {
  const query = { ...route.query }
  if (searchQuery.value) query.q = searchQuery.value
  else delete query.q
  if (subtitleOnly.value) query.has_subtitle = '1'
  if (learnedFilter.value !== 'all') query.learned = learnedFilter.value
  else delete query.learned
  if (!subtitleOnly.value) delete query.has_subtitle
  const page = Math.max(1, Math.ceil(videos.value.length / PAGE_SIZE))
  if (page > 1) query.page = String(page)
  else delete query.page
  const returnTo = router.resolve({ name: 'blogger-detail', params: { id: subId.value }, query,
    hash: `#video-${videoId}` }).fullPath
  const index = videos.value.findIndex(v => v.id === videoId)
  const context = { videoId, index, loadedCount: videos.value.length, expandedVideoId: expandedVideoId.value,
    offset: document.getElementById(`video-${videoId}`)?.getBoundingClientRect().top ?? 100,
    neighbors: videos.value.slice(Math.max(0, index - 2), index + 4).map(v => v.id) }
  saveBloggerContext(bloggerContextKey(identityKey.value, subId.value, currentQueryState()), context)
  // Persist the anchor in the history entry that browser Back will revisit.
  await router.replace(returnTo)
  if (!disposed) emit('open-workspace', { url: item.url, title: item.title, returnTo })
}

function backToList() {
  stopBatchPolling()
  emit('back')
}

async function restorePosition(context, anchorId, ticket) {
  await nextTick()
  if (disposed || ticket !== loadEpoch) return
  let target = videos.value.find(v => v.id === anchorId)
  if (!target && anchorId) {
    missingVideo.value = { id: anchorId }
    target = context?.neighbors.map(id => videos.value.find(v => v.id === id)).find(Boolean)
      || videos.value[Math.min(context?.index || 0, Math.max(0, videos.value.length - 1))]
  }
  if (context?.expandedVideoId && videos.value.some(v => v.id === context.expandedVideoId)) {
    expandedVideoId.value = context.expandedVideoId
    await listPages(subId.value, context.expandedVideoId)
    await nextTick()
  }
  if (disposed || ticket !== loadEpoch) return
  const element = target && document.getElementById(`video-${target.id}`)
  if (element) {
    restoredVideoId.value = target.id
    clearTimeout(restoreTimer)
    restoreTimer = setTimeout(() => { restoredVideoId.value = null }, 3000)
    const offset = Math.max(88, Math.min(context?.offset ?? 160, window.innerHeight - 120))
    window.scrollTo({ top: Math.max(0, window.scrollY + element.getBoundingClientRect().top - offset), behavior: 'instant' })
  } else window.scrollTo({ top: 0, behavior: 'instant' })
}

async function loadAll() {
  const ticket = ++loadEpoch
  const state = currentQueryState()
  searchQuery.value = state.q
  learnedFilter.value = state.learned
  subtitleOnly.value = state.subtitle
  expandedVideoId.value = null
  missingVideo.value = null
  const anchorId = /^#video-\d+$/.test(route.hash) ? Number(route.hash.slice(7)) : null
  const context = anchorId ? readBloggerContext(bloggerContextKey(identityKey.value, subId.value, state)) : null
  const saved = context?.videoId === anchorId ? context : null
  const requestedPage = Number(route.query.page)
  let restorePages = Number.isInteger(requestedPage) ? Math.max(1, Math.min(100, requestedPage)) : 1
  const [, result] = await Promise.all([listBloggers(), refreshVideos({ anchorId }), listBatches(subId.value)])
  if (disposed || ticket !== loadEpoch) return
  if (Number.isInteger(result?.anchor_index)) restorePages = Math.max(restorePages, Math.ceil((result.anchor_index + 1) / PAGE_SIZE))
  if (saved) restorePages = Math.max(restorePages, Math.ceil(saved.loadedCount / PAGE_SIZE))
  for (let page = 1; page < restorePages && videosHasMore.value; page += 1) {
    if (disposed || ticket !== loadEpoch || !await refreshVideos({ append: true })) return
  }
  ensureSyncPolling()
  await restorePosition(saved, anchorId, ticket)
}

async function revealMissingVideo() {
  const id = missingVideo.value?.id
  if (!id) return
  await router.replace({ name: 'blogger-detail', params: { id: subId.value }, hash: `#video-${id}` })
}

watch(subId, async () => {
  if (!subId.value) return
  await loadAll()
})

watch(() => [route.query.q, route.query.learned, route.query.has_subtitle], async () => {
  if (route.name !== 'blogger-detail' || !subId.value) return
  const state = currentQueryState()
  if (state.q === searchQuery.value && state.learned === learnedFilter.value && state.subtitle === subtitleOnly.value) return
  await loadAll()
})
watch(identityKey, loadAll)
onBeforeUnmount(() => { disposed = true; loadEpoch += 1; clearTimeout(toastTimer); clearTimeout(restoreTimer) })

onMounted(loadAll)
</script>

<template>
  <div class="blogger-detail">
    <div class="detail-container">
      <header class="detail-header">
        <button class="btn-back" @click="backToList">← 返回博主列表</button>
        <div class="detail-title-block">
          <div class="detail-title-row">
            <template v-if="editingAlias">
              <input
                v-model="aliasValue"
                class="alias-input"
                maxlength="64"
                placeholder="备注名（留空显示昵称）"
                @keyup.enter="saveAlias"
                @keyup.esc="editingAlias = false"
              />
              <button class="btn-icon-only" title="保存" @click="saveAlias">✓</button>
              <button class="btn-icon-only" title="取消" @click="editingAlias = false">✗</button>
            </template>
            <template v-else>
              <h1 class="detail-title">{{ displayNameOf(blogger) }}</h1>
              <button class="btn-icon-only" title="编辑备注名" @click="startEditAlias">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="btn-icon">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                </svg>
              </button>
            </template>
          </div>
          <p v-if="blogger" class="detail-subtitle">
            {{ blogger.follower_count || 0 }} 粉丝 · {{ videosMatchedTotal }} 个投稿 · 有字幕 {{ videosSubtitleTotal }} · 已整理 {{ videosLearnedTotal }}
          </p>
        </div>
      </header>

      <section class="sync-bar" :class="`sync-bar--${blogger?.sync_status || 'none'}`">
        <div class="sync-bar-main">
          <span class="sync-dot" :class="{ pulse: isSyncActive() }"></span>
          <span class="sync-bar-label">{{ syncLabel() }}</span>
          <span v-if="isSyncActive()" class="sync-bar-progress">{{ syncProgressText() }}</span>
        </div>
        <div class="sync-bar-actions">
          <template v-if="isSyncActive()">
            <button class="btn-ghost btn-ghost--sm" :disabled="pending.cancelSync" @click="handleCancelSync">取消同步</button>
          </template>
          <template v-else>
            <button class="btn-ghost btn-ghost--sm" :disabled="pending.sync" @click="handleSync('incremental')">同步</button>
            <button class="btn-ghost btn-ghost--sm" :disabled="pending.sync" @click="handleDeepSync">深度同步</button>
          </template>
        </div>
      </section>

      <section class="toolbar">
        <div class="search-wrap">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="search-icon">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-4.35-4.35M17 11a6 6 0 11-12 0 6 6 0 0112 0z"/>
          </svg>
          <input
            v-model="searchQuery"
            class="search-input"
            type="search"
            placeholder="搜索投稿标题…"
            @keyup.enter="handleSearch"
          />
        </div>
        <button class="btn-ghost" @click="handleSearch">搜索</button>
        <div class="filter-chips">
          <button class="filter-chip" :class="{ active: learnedFilter === 'all' }" @click="setLearnedFilter('all')">全部</button>
          <button class="filter-chip" :class="{ active: learnedFilter === 'learned' }" @click="setLearnedFilter('learned')">已整理</button>
          <button class="filter-chip" :class="{ active: learnedFilter === 'unlearned' }" @click="setLearnedFilter('unlearned')">未整理</button>
        </div>
        <label class="subtitle-filter"><input v-model="subtitleOnly" type="checkbox" @change="toggleSubtitleOnly" />仅看有字幕</label>
        <div class="toolbar-spacer"></div>
        <select v-model="batchMode" class="mode-select" aria-label="批量模式">
          <option value="full">完整学习资料</option>
          <option value="subtitle">仅字幕</option>
          <option value="meta">仅解析</option>
        </select>
        <button class="btn-ghost" @click="selectionMode = !selectionMode; selected = new Set()">
          {{ selectionMode ? '退出多选' : '多选' }}
        </button>
        <template v-if="selectionMode">
          <button class="btn-ghost" @click="toggleSelectAll">
            {{ selected.size === videos.length && videos.length ? '取消全选' : '全选已加载' }}
          </button>
          <button class="btn-primary" :disabled="pending.createBatch || !selected.size" @click="handleCreateBatch">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="btn-icon">
              <path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/>
            </svg>
            {{ pending.createBatch ? '创建中…' : `批量生成（${selected.size}）` }}
          </button>
        </template>
      </section>

      <div v-if="missingVideo" class="return-notice" role="status">刚才的视频状态已更新，不在当前筛选中。
        <button class="btn-ghost btn-ghost--sm" @click="revealMissingVideo">查看该视频</button>
      </div>
      <div v-if="videosLoading && !videos.length" class="detail-empty">
        <div class="loading-spinner"></div>
      </div>
      <div v-else-if="!videos.length" class="detail-empty">
        <p class="empty-hint">
          {{ learnedFilter !== 'all' || subtitleOnly || searchQuery ? '没有匹配的投稿' : '还没有投稿目录' }}
        </p>
        <p v-if="learnedFilter === 'all' && !subtitleOnly && !searchQuery" class="empty-sub">点上方「同步」拉取该 UP 主的投稿</p>
      </div>

      <template v-else>
        <div class="video-list">
          <article v-for="item in videos" :id="`video-${item.id}`" :key="item.id" class="video-card" :class="{ 'video-card--selected': selected.has(item.id), 'video-card--restored': restoredVideoId === item.id }">
            <label v-if="selectionMode" class="video-check">
              <input type="checkbox" :checked="selected.has(item.id)" @change="toggleSelect(item.id)" />
            </label>
            <div class="video-thumb-wrap" @click="toggleExpand(item)">
              <img
                v-if="item.cover"
                :src="thumbnailSrc(item.cover)"
                alt=""
                class="video-thumb"
                loading="lazy"
                referrerpolicy="no-referrer"
              />
              <div v-else class="video-thumb video-thumb--placeholder">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                </svg>
              </div>
              <span v-if="item.duration" class="video-duration">{{ formatDuration(item.duration) }}</span>
              <span v-if="item.page_count > 1" class="video-parts">{{ item.page_count }}P</span>
            </div>
            <div class="video-main" @click="toggleExpand(item)">
              <h3 class="video-title">
                <span class="video-title-text">{{ item.title }}</span>

              </h3>
              <ContentBadges :content="item.content" :total-parts="item.page_count || 1" :subtitle-parts="item.subtitle_parts" :organized-parts="item.organized_parts" />
              <p class="video-meta">
                <span>{{ formatDate(item.published_at) }}</span>
                <span v-if="taskForItem(item)" class="task-live">{{ taskForItem(item).message || taskForItem(item).status }}</span>
              </p>
            </div>
            <div class="video-actions">
              <button class="btn-ghost" title="在工作台打开并生成" @click="openWorkspace(item)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="btn-icon">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/>
                  <path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                工作台
              </button>
            </div>

            <div v-if="expandedVideoId === item.id" class="parts-panel">
              <div v-if="pagesLoading" class="loading-spinner loading-spinner--sm"></div>
              <template v-else>
                <div v-for="part in pages" :key="part.cid" class="part-row">
                  <span class="part-index">P{{ part.page }}</span>
                  <span class="part-title">{{ part.part_title || item.title }}</span>
                  <ContentBadges :content="part.content" />
                  <button class="btn-ghost btn-ghost--sm" @click="openWorkspace({ ...part, title: item.title }, item.id)">工作台</button>
                </div>
              </template>
            </div>
          </article>
        </div>

        <div class="list-footer">
          <span class="list-count">共 {{ videosMatchedTotal }} · 有字幕 {{ videosSubtitleTotal }} · 已整理 {{ videosLearnedTotal }}</span>
          <button v-if="videosHasMore" class="btn-ghost" :disabled="videosLoading" @click="loadMore">
            {{ videosLoading ? '加载中…' : `加载更多（已显示 ${videos.length}）` }}
          </button>
        </div>
      </template>

      <section v-if="batches.length" class="batch-section">
        <h2 class="section-title">批量任务</h2>
        <div v-for="batch in batches" :key="batch.id" class="batch-card" @click="openBatch(batch)">
          <div class="batch-head">
            <span class="chip" :class="toneFor(batch.status)">{{ batchStatusLabel(batch.status) }}</span>
            <span class="batch-counts">{{ batch.done_count }}/{{ batch.total }} 完成<template v-if="batch.failed_count"> · {{ batch.failed_count }} 失败</template></span>
            <span class="batch-time">{{ batch.created_at }}</span>
          </div>
          <div class="batch-progress"><div class="batch-progress-bar" :class="toneFor(batch.status)" :style="{ width: `${batch.total ? Math.round(((batch.done_count + batch.failed_count) / batch.total) * 100) : 0}%` }"></div></div>
          <div v-if="currentBatch && currentBatch.id === batch.id" class="batch-items" @click.stop>
            <div v-if="batchLoading && !currentBatch?.items?.length" class="loading-spinner loading-spinner--sm"></div>
            <template v-else>
              <div v-for="item in currentBatch?.items || []" :key="item.id" class="batch-item-row">
                <span class="batch-item-title">{{ item.title }}</span>
                <span class="batch-item-status" :class="toneFor(item.status)">{{ statusLabel(item) }}</span>
              </div>
              <div class="batch-actions">
                <button v-if="['queued', 'running'].includes(currentBatch.status)"
                        class="btn-ghost" :disabled="pending.action === 'pause'" @click="handleBatchAction('pause')">暂停</button>
                <button v-if="currentBatch.status === 'paused'"
                        class="btn-ghost" :disabled="pending.action === 'resume'" @click="handleBatchAction('resume')">恢复</button>
                <button v-if="currentBatch.failed_count"
                        class="btn-ghost" :disabled="pending.action === 'retry_failed'" @click="handleBatchAction('retry_failed')">重试失败</button>
                <button v-if="['queued', 'running', 'paused'].includes(currentBatch.status)"
                        class="btn-ghost btn-ghost--danger" :disabled="pending.action === 'cancel'" @click="handleBatchAction('cancel')">取消</button>
              </div>
            </template>
          </div>
        </div>
      </section>
    </div>

    <ConfirmDialog
      :visible="!!confirmation"
      :title="confirmation?.title || '确认操作'"
      :message="confirmation?.message || ''"
      confirm-label="确定"
      cancel-label="取消"
      danger
      @confirm="closeConfirmation(true)"
      @close="closeConfirmation(false)"
    />

    <Transition name="toast">
      <div v-if="toast" class="app-toast" :class="`app-toast--${toast.type}`" @click="toast = null">
        <svg v-if="toast.type === 'success'" viewBox="0 0 20 20" fill="currentColor" class="app-toast-icon">
          <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
        </svg>
        <svg v-else viewBox="0 0 20 20" fill="currentColor" class="app-toast-icon">
          <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
        </svg>
        <span>{{ toast.message }}</span>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.subtitle-filter { display: inline-flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: .82rem; cursor: pointer; min-height: 44px; }
.return-notice { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; padding: 12px; border: 1px solid var(--border); border-radius: 12px; color: var(--text-secondary); }
.video-card--restored { border-color: var(--accent-cyan); box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent-cyan) 25%, transparent); }
.video-main > .content-badges { margin-top: 6px; }
.blogger-detail {
  min-height: calc(100vh - 60px);
  background: var(--bg-primary);
  padding: 6rem 2rem 3rem;
}
.detail-container { max-width: 1100px; margin: 0 auto; display: flex; flex-direction: column; gap: 1.15rem; }

.detail-header { display: flex; align-items: center; gap: 16px; }
.btn-back {
  border: none; background: none; color: var(--accent-cyan);
  cursor: pointer; font-size: 0.88rem; padding: 0;
}
.btn-back:hover { text-decoration: underline; }
.detail-title-row { display: flex; align-items: center; gap: 8px; }
.detail-title {
  font-size: 1.5rem; font-weight: 700; margin: 0;
  background: linear-gradient(135deg, var(--accent-blue), var(--accent-cyan));
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
.detail-subtitle { margin: 0.35rem 0 0; color: var(--text-muted); font-size: 0.85rem; }
.alias-input {
  padding: 0.4rem 0.65rem; font-size: 0.95rem;
  border: 1px solid var(--accent-blue); border-radius: 8px;
  background: rgba(255, 255, 255, 0.06); color: var(--text-primary);
}
.alias-input:focus { outline: none; }
.btn-icon-only {
  border: none; background: none; color: var(--text-muted); cursor: pointer;
  padding: 2px; display: grid; place-items: center; border-radius: 6px;
}
.btn-icon-only:hover { color: var(--accent-cyan); background: var(--bg-card-hover); }
.btn-icon { width: 15px; height: 15px; }

.sync-bar {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 0.75rem 1.15rem; border-radius: 14px;
  background: var(--bg-card); border: 1px solid var(--border);
}
.sync-bar--paused, .sync-bar--failed { border-color: rgba(248, 113, 113, 0.35); background: rgba(248, 113, 113, 0.08); }
.sync-bar--running, .sync-bar--queued { border-color: rgba(6, 182, 212, 0.35); background: rgba(6, 182, 212, 0.08); }
.sync-bar-main { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 200px; font-size: 0.84rem; color: var(--text-secondary); }
.sync-bar-label { color: var(--text-primary); }
.sync-bar-progress { color: var(--text-muted); font-size: 0.78rem; }
.sync-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-muted); flex-shrink: 0; }
.sync-dot.pulse { background: var(--accent-cyan); animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: 0.35; } }
.sync-bar-actions { display: flex; gap: 8px; }

.toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.search-wrap { position: relative; flex: 1; min-width: 200px; }
.search-icon {
  position: absolute; left: 12px; top: 50%; transform: translateY(-50%);
  width: 16px; height: 16px; color: var(--text-muted); pointer-events: none;
}
.search-input {
  width: 100%; padding: 0.65rem 0.9rem 0.65rem 2.3rem;
  border: 1px solid var(--border); border-radius: 12px;
  background: var(--bg-card); color: var(--text-primary); font-size: 0.88rem;
}
.search-input:focus { outline: none; border-color: var(--accent-blue); }
.search-input::placeholder { color: var(--text-muted); }
.filter-chips { display: flex; gap: 6px; }
.filter-chip {
  padding: 0.45rem 0.9rem; border-radius: 999px; font-size: 0.8rem; cursor: pointer;
  border: 1px solid var(--border); background: var(--bg-card); color: var(--text-secondary);
  transition: all 0.15s ease;
}
.filter-chip:hover { border-color: var(--border-hover); color: var(--text-primary); }
.filter-chip.active {
  background: rgba(59, 130, 246, 0.18); border-color: rgba(59, 130, 246, 0.5); color: var(--accent-blue);
}
.toolbar-spacer { flex: 1; }
.mode-select {
  padding: 0.6rem 0.75rem; border: 1px solid var(--border); border-radius: 12px;
  background: var(--bg-card); color: var(--text-secondary); font-size: 0.82rem;
}

.btn-primary {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 0.6rem 1.1rem; border: none; border-radius: 12px;
  background: linear-gradient(135deg, var(--accent-blue), var(--accent-cyan));
  color: #fff; font-weight: 600; font-size: 0.85rem; cursor: pointer;
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.btn-primary:hover:not(:disabled) { opacity: 0.92; transform: translateY(-1px); }
.btn-primary:disabled { opacity: 0.5; cursor: default; }

.btn-ghost {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 0.5rem 0.85rem; border: 1px solid var(--border); border-radius: 10px;
  background: var(--bg-card); color: var(--text-secondary);
  font-size: 0.8rem; cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
}
.btn-ghost:hover:not(:disabled) { border-color: var(--border-hover); color: var(--text-primary); background: var(--bg-card-hover); }
.btn-ghost:disabled { opacity: 0.5; cursor: default; }
.btn-ghost--danger:hover:not(:disabled) { color: #f87171; border-color: rgba(248, 113, 113, 0.4); }
.btn-ghost--sm { padding: 0.35rem 0.7rem; font-size: 0.75rem; }

.detail-empty {
  text-align: center; padding: 4rem 1rem;
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 16px;
}
.empty-hint { margin: 0; color: var(--text-secondary); }
.empty-sub { margin: 0.4rem 0 0; color: var(--text-muted); font-size: 0.85rem; }
.loading-spinner {
  width: 26px; height: 26px; margin: 0 auto;
  border: 3px solid rgba(59, 130, 246, 0.2); border-top-color: var(--accent-blue);
  border-radius: 50%; animation: spin 0.8s linear infinite;
}
.loading-spinner--sm { width: 18px; height: 18px; }
@keyframes spin { to { transform: rotate(360deg); } }

.video-list { display: flex; flex-direction: column; gap: 0.75rem; }
.video-card {
  display: flex; align-items: center; gap: 12px; padding: 0.9rem 1rem;
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 16px;
  flex-wrap: wrap; backdrop-filter: blur(12px);
  transition: border-color 0.15s ease, background 0.15s ease;
}
.video-card:hover { border-color: var(--border-hover); background: var(--bg-card-hover); }
.video-card--selected { border-color: rgba(59, 130, 246, 0.55); }
.video-check input { width: 17px; height: 17px; accent-color: var(--accent-blue); cursor: pointer; }

.video-thumb-wrap { position: relative; cursor: pointer; flex-shrink: 0; }
.video-thumb {
  width: 124px; height: 70px; object-fit: cover; border-radius: 10px; display: block;
  background: var(--bg-secondary);
}
.video-thumb--placeholder {
  display: grid; place-items: center; color: var(--text-muted); border: 1px solid var(--border);
}
.video-thumb--placeholder svg { width: 26px; height: 26px; }
.video-duration, .video-parts {
  position: absolute; background: rgba(15, 23, 42, 0.82); color: #fff;
  font-size: 0.68rem; padding: 1px 6px; border-radius: 6px;
}
.video-duration { right: 5px; bottom: 5px; }
.video-parts { left: 5px; top: 5px; }

.video-main { flex: 1; min-width: 180px; cursor: pointer; }
.video-title { display: flex; gap: 8px; align-items: baseline; margin: 0; font-size: 0.92rem; font-weight: 600; color: var(--text-primary); }
.video-title-text { overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.video-meta { margin: 0.45rem 0 0; font-size: 0.76rem; color: var(--text-muted); display: flex; gap: 10px; align-items: center; }
.task-live { color: var(--accent-cyan); }

.chip {
  font-size: 0.7rem; padding: 2px 10px; border-radius: 999px; flex-shrink: 0; font-weight: 500;
}
.chip--ok, .tone-ok { color: #34d399; background: rgba(52, 211, 153, 0.12); }
.tone-bad { color: #f87171; background: rgba(248, 113, 113, 0.12); }
.tone-busy { color: var(--accent-cyan); background: rgba(6, 182, 212, 0.12); }
.batch-item-status.tone-ok, .batch-item-status.tone-bad, .batch-item-status.tone-busy { background: none; padding: 0; }

.video-actions { display: flex; gap: 6px; }

.parts-panel {
  flex-basis: 100%; border-top: 1px dashed var(--border); padding-top: 0.75rem;
  display: flex; flex-direction: column; gap: 6px;
}
.part-row { display: flex; align-items: center; gap: 10px; font-size: 0.83rem; color: var(--text-secondary); }
.part-index { color: var(--text-muted); min-width: 2.2em; }
.part-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.list-footer {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 0.5rem 0.25rem;
}
.list-count { font-size: 0.8rem; color: var(--text-muted); }

.batch-section { margin-top: 1rem; }
.section-title { font-size: 1.15rem; font-weight: 700; margin: 0 0 0.9rem; color: var(--text-primary); }
.batch-card {
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 16px;
  padding: 1rem 1.15rem; margin-bottom: 0.75rem; cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.batch-card:hover { border-color: var(--border-hover); background: var(--bg-card-hover); }
.batch-head { display: flex; gap: 12px; align-items: center; font-size: 0.85rem; }
.batch-counts { color: var(--text-secondary); }
.batch-time { margin-left: auto; color: var(--text-muted); font-size: 0.74rem; }
.batch-progress {
  height: 5px; margin-top: 0.75rem; border-radius: 999px;
  background: rgba(255, 255, 255, 0.07); overflow: hidden;
}
.batch-progress-bar { height: 100%; border-radius: 999px; transition: width 0.4s ease; }
.batch-progress-bar.tone-ok { background: linear-gradient(90deg, #34d399, #06b6d4); }
.batch-progress-bar.tone-bad { background: linear-gradient(90deg, #f87171, #fbbf24); }
.batch-progress-bar.tone-busy { background: linear-gradient(90deg, var(--accent-blue), var(--accent-cyan)); }
.batch-items {
  margin-top: 0.85rem; border-top: 1px dashed var(--border); padding-top: 0.85rem; cursor: default;
}
.batch-item-row { display: flex; gap: 10px; align-items: center; padding: 0.2rem 0; font-size: 0.82rem; }
.batch-item-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-secondary); }
.batch-item-status { font-size: 0.78rem; }
.batch-actions { display: flex; gap: 8px; margin-top: 0.85rem; }

.app-toast {
  position: fixed; bottom: 2rem; left: 50%; transform: translateX(-50%);
  display: flex; align-items: center; gap: 0.55rem;
  padding: 0.8rem 1.3rem; border-radius: 12px;
  font-size: 0.875rem; color: #fff; z-index: 9999; cursor: pointer;
  max-width: 90vw; box-shadow: 0 8px 28px rgba(0, 0, 0, 0.35);
}
.app-toast--error { background: rgba(239, 68, 68, 0.95); box-shadow: 0 8px 28px rgba(239, 68, 68, 0.3); }
.app-toast--success { background: rgba(16, 185, 129, 0.95); box-shadow: 0 8px 28px rgba(16, 185, 129, 0.3); }
.app-toast-icon { width: 18px; height: 18px; flex-shrink: 0; }
.toast-enter-active { animation: toast-in 0.25s ease-out; }
.toast-leave-active { animation: toast-out 0.2s ease-in; }
@keyframes toast-in { from { opacity: 0; transform: translateX(-50%) translateY(1rem); } to { opacity: 1; transform: translateX(-50%) translateY(0); } }
@keyframes toast-out { from { opacity: 1; transform: translateX(-50%) translateY(0); } to { opacity: 0; transform: translateX(-50%) translateY(1rem); } }
</style>

<style scoped>
@media (max-width: 600px) {
  .blogger-detail { padding: 5rem 1rem 2rem; }
  .detail-header { align-items: flex-start; flex-direction: column; }
  .video-thumb { width: 96px; height: 54px; }
  .video-main { min-width: 0; flex-basis: calc(100% - 112px); }
  .video-actions { width: 100%; justify-content: flex-end; }
  .part-row { flex-wrap: wrap; gap: 8px; }
  .part-title { min-width: 100px; }
  .filter-chip { min-height: 44px; }
  .list-footer { flex-wrap: wrap; }
}
</style>
