<script setup>
import { ref, watch, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth.js'
import ConfirmDialog from './ConfirmDialog.vue'

const { getAuthHeaders } = useAuth()
const route = useRoute()
const router = useRouter()
const props = defineProps({
  activeTasks: { type: Array, default: () => [] }
})
const emit = defineEmits(['select-item'])

// 后台任务完成时自动刷新历史记录（带防抖，避免连续触发）
const _prevTaskHashes = ref(new Set())
let _refreshTimer = null
watch(() => props.activeTasks.length, () => {
  const newTasks = props.activeTasks
  const newHashes = new Set(newTasks.map(t => t.url_hash))
  const disappeared = [..._prevTaskHashes.value].filter(h => !newHashes.has(h))
  _prevTaskHashes.value = newHashes

  if (disappeared.length > 0) {
    clearTimeout(_refreshTimer)
    _refreshTimer = setTimeout(() => fetchHistoryPage(), 800)
  }
})

onUnmounted(() => {
  clearTimeout(_refreshTimer)
})

function getTaskForUrl(urlHash) {
  return props.activeTasks.find(t => t.url_hash === urlHash)
}

function getElapsedSeconds(task) {
  const startedAt = Date.parse(task.started_at || task.created_at || '')
  if (!Number.isFinite(startedAt)) return 0
  return Math.max(0, Math.floor((Date.now() - startedAt) / 1000))
}

function getRemainingEstimate(task) {
  const elapsed = getElapsedSeconds(task)
  return Math.max(0, task.estimated_seconds - elapsed)
}

function formatRemaining(task) {
  if (!task) return ''
  if (task.status === 'queued') {
    return task.queue_position ? `队列第 ${task.queue_position} 位` : '等待调度'
  }
  const elapsed = getElapsedSeconds(task)
  const remaining = Math.max(0, task.estimated_seconds - elapsed)
  if (remaining > 0) {
    const m = Math.floor(remaining / 60)
    const s = remaining % 60
    return m > 0 ? `预计还需 ${m} 分 ${s} 秒` : `预计还需 ${s} 秒`
  }
  // 超出预估，显示已用时
  const em = Math.floor(elapsed / 60)
  const es = elapsed % 60
  return `已转录 ${em} 分 ${es} 秒，即将完成`
}

const activeStatuses = new Set(['queued', 'downloading', 'transcribing', 'generating'])

function isActiveItem(item) {
  return Boolean(getTaskForUrl(item.url_hash)) || activeStatuses.has(item.status)
}

function taskStageLabel(task, item) {
  const status = task?.status || item.status
  return {
    queued: '等待后台处理',
    downloading: '正在下载音频',
    transcribing: 'Whisper 转录中',
    generating: 'AI 生成中',
  }[status] || '后台处理中'
}

const historySearchQuery = ref(String(route.query.q || ''))
const historyTags = ref([])
const historyActiveTag = ref(String(route.query.tag || ''))
const historyPlatform = ref(String(route.query.platform || ''))
const historySort = ref(route.query.sort === 'oldest' ? 'oldest' : 'newest')
const historyItems = ref([])
const historyTotal = ref(0)
const historyStats = ref(null)
const historyLoading = ref(false)
const historyLoadingMore = ref(false)
const historyHasMore = ref(false)
const deletingHistoryId = ref(null)
const selectionMode = ref(false)
const selectedIds = ref(new Set())
const batchDeleting = ref(false)
const errorMessage = ref('')
let errorTimer = null
function showError(msg) {
  errorMessage.value = msg
  clearTimeout(errorTimer)
  errorTimer = setTimeout(() => { errorMessage.value = '' }, 4000)
}
const expandedGroups = ref({}) // { groupKey: true/false }
const expandedTaskItem = ref(null) // url_hash of expanded transcribing item
const cancelingTaskId = ref(null)
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

function syncRouteQuery() {
  const query = {}
  if (historySearchQuery.value) query.q = historySearchQuery.value
  if (historyActiveTag.value) query.tag = historyActiveTag.value
  if (historyPlatform.value) query.platform = historyPlatform.value
  if (historySort.value !== 'newest') query.sort = historySort.value
  router.replace({ name: 'history', query })
}

watch(() => route.query, query => {
  const nextSearch = String(query.q || '')
  const nextTag = String(query.tag || '')
  const nextPlatform = String(query.platform || '')
  const nextSort = query.sort === 'oldest' ? 'oldest' : 'newest'
  if (
    nextSearch === historySearchQuery.value &&
    nextTag === historyActiveTag.value &&
    nextPlatform === historyPlatform.value &&
    nextSort === historySort.value
  ) return
  historySearchQuery.value = nextSearch
  historyActiveTag.value = nextTag
  historyPlatform.value = nextPlatform
  historySort.value = nextSort
  fetchHistoryPage()
})

function toggleTaskDetail(item) {
  if (isActiveItem(item)) {
    expandedTaskItem.value = expandedTaskItem.value === item.url_hash ? null : item.url_hash
  }
}

async function cancelTask(taskId) {
  if (!await requestConfirmation('确定要取消此转录任务？', '停止转录')) return
  cancelingTaskId.value = taskId
  try {
    const res = await fetch(`/api/tasks/${taskId}/cancel`, { method: 'POST', headers: getAuthHeaders() })
    if (res.ok) {
      // 刷新历史记录
      fetchHistoryPage()
    } else {
      showError('取消失败')
    }
  } catch { showError('取消失败') } finally {
    cancelingTaskId.value = null
    expandedTaskItem.value = null
  }
}

async function deleteTranscribingItem(item) {
  if (!await requestConfirmation(`确定删除「${item.video_title || '未标题'}」？`, '删除历史记录')) return
  // 先取消关联的后台任务
  const task = getTaskForUrl(item.url_hash)
  if (task) {
    try { await fetch(`/api/tasks/${task.task_id}/cancel`, { method: 'POST', headers: getAuthHeaders() }) } catch {}
  }
  // 删除历史记录
  try {
    await fetch(`/api/history/${item.url_hash}`, { method: 'DELETE', headers: getAuthHeaders() })
    historyItems.value = historyItems.value.filter(h => h.url_hash !== item.url_hash)
    historyTotal.value = Math.max(0, historyTotal.value - 1)
  } catch { showError('删除失败') }
}

async function fetchHistoryPage() {
  historyLoading.value = true
  try {
    const params = new URLSearchParams()
    if (historySearchQuery.value) params.set('q', historySearchQuery.value)
    if (historyActiveTag.value) params.set('tag', historyActiveTag.value)
    if (historyPlatform.value) params.set('platform', historyPlatform.value)
    params.set('sort', historySort.value)
    params.set('limit', '12')
    params.set('offset', '0')

    const authH = getAuthHeaders()
    const [historyRes, tagsRes, statsRes] = await Promise.all([
      fetch(`/api/history?${params}`, { headers: authH }),
      fetch('/api/history/tags', { headers: authH }),
      fetch('/api/history/stats', { headers: authH }),
    ])

    if (historyRes.ok) {
      const data = await historyRes.json()
      historyItems.value = data.items || []
      historyTotal.value = data.total || 0
      historyHasMore.value = historyItems.value.length < historyTotal.value
    } else {
      console.error('History API error:', historyRes.status, await historyRes.text())
    }
    if (tagsRes.ok) historyTags.value = await tagsRes.json()
    if (statsRes.ok) historyStats.value = await statsRes.json()
  } catch (e) {
    console.error('fetchHistoryPage error:', e)
    showError('加载历史记录失败，请稍后重试')
  } finally {
    historyLoading.value = false
  }
}

async function loadMoreHistory() {
  historyLoadingMore.value = true
  try {
    const params = new URLSearchParams()
    if (historySearchQuery.value) params.set('q', historySearchQuery.value)
    if (historyActiveTag.value) params.set('tag', historyActiveTag.value)
    if (historyPlatform.value) params.set('platform', historyPlatform.value)
    params.set('sort', historySort.value)
    params.set('limit', '12')
    params.set('offset', String(historyItems.value.length))

    const res = await fetch(`/api/history?${params}`, { headers: getAuthHeaders() })
    if (res.ok) {
      const data = await res.json()
      historyItems.value.push(...(data.items || []))
      historyHasMore.value = historyItems.value.length < historyTotal.value
    }
  } catch { showError('加载失败，请稍后重试') } finally {
    historyLoadingMore.value = false
  }
}

function handleHistorySearch() {
  syncRouteQuery()
  fetchHistoryPage()
}

function setHistoryTag(tag) {
  historyActiveTag.value = historyActiveTag.value === tag ? '' : tag
  syncRouteQuery()
  fetchHistoryPage()
}

function setHistorySort(sort) {
  historySort.value = sort
  syncRouteQuery()
  fetchHistoryPage()
}

function setHistoryPlatform(platform) {
  historyPlatform.value = historyPlatform.value === platform ? '' : platform
  syncRouteQuery()
  fetchHistoryPage()
}

async function toggleFavorite(item) {
  try {
    const targetId = item.is_multipart ? item.parts[0]?.id : item.id
    if (!targetId) return
    const res = await fetch(`/api/history/${targetId}/favorite`, { method: 'POST', headers: getAuthHeaders() })
    if (res.ok) {
      const data = await res.json()
      item.is_favorite = data.is_favorite
    }
  } catch { showError('操作失败，请稍后重试') }
}

async function deleteHistoryItem(item) {
  // 转录中的记录需要同时取消后台任务
  if (isActiveItem(item)) {
    return deleteTranscribingItem(item)
  }
  if (item.is_multipart) {
    if (!await requestConfirmation(`确定删除「${item.video_title}」的全部 ${item.parts_count} 个分P？`, '删除全部分 P')) return
    try {
      deletingHistoryId.value = item.id
      const authH = getAuthHeaders()
      await Promise.all(item.parts.map(p => fetch(`/api/history/${p.id}`, { method: 'DELETE', headers: authH })))
      historyItems.value = historyItems.value.filter(h => h.id !== item.id)
    } catch { showError('删除失败，请稍后重试') } finally {
      deletingHistoryId.value = null
    }
    return
  }
  if (!await requestConfirmation(`确定删除「${item.video_title}」？`, '删除历史记录')) return
  try {
    deletingHistoryId.value = item.id
    await fetch(`/api/history/${item.id}`, { method: 'DELETE', headers: getAuthHeaders() })
    historyItems.value = historyItems.value.filter(h => h.id !== item.id)
  } catch { showError('删除失败，请稍后重试') } finally {
    deletingHistoryId.value = null
  }
}

function selectHistory(item) {
  if (isActiveItem(item)) {
    toggleTaskDetail(item)
    return
  }
  emit('select-item', item)
}

// ── 批量选择 ──

function getItemHashes(item) {
  if (item.is_multipart) {
    return (item.parts || []).map(p => p.id)
  }
  return [item.id]
}

function toggleSelectionMode() {
  selectionMode.value = !selectionMode.value
  if (!selectionMode.value) {
    selectedIds.value = new Set()
  }
}

function toggleSelectItem(item) {
  const ids = getItemHashes(item)
  const newSet = new Set(selectedIds.value)
  const allSelected = ids.every(id => newSet.has(id))
  if (allSelected) {
    ids.forEach(id => newSet.delete(id))
  } else {
    ids.forEach(id => newSet.add(id))
  }
  selectedIds.value = newSet
}

function isItemSelected(item) {
  const ids = getItemHashes(item)
  return ids.length > 0 && ids.every(id => selectedIds.value.has(id))
}

function toggleSelectAll() {
  const allHashes = historyItems.value.flatMap(item => getItemHashes(item))
  const allSelected = allHashes.length > 0 && allHashes.every(id => selectedIds.value.has(id))
  if (allSelected) {
    selectedIds.value = new Set()
  } else {
    selectedIds.value = new Set(allHashes)
  }
}

async function batchDeleteSelected() {
  const count = selectedIds.value.size
  if (count === 0) return
  if (!await requestConfirmation(`确定删除选中的 ${count} 条记录？`, '批量删除')) return

  batchDeleting.value = true
  try {
    const res = await fetch('/api/history/batch-delete', {
      method: 'POST',
      headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ url_hashes: [...selectedIds.value] }),
    })
    if (res.ok) {
      const before = historyItems.value.length
      historyItems.value = historyItems.value.filter(item => {
        const hashes = getItemHashes(item)
        return !hashes.some(id => selectedIds.value.has(id))
      })
      historyTotal.value -= before - historyItems.value.length
      selectedIds.value = new Set()
      selectionMode.value = false
      // 刷新标签和统计
      const [tagsRes, statsRes] = await Promise.all([
        fetch('/api/history/tags', { headers: getAuthHeaders() }),
        fetch('/api/history/stats', { headers: getAuthHeaders() }),
      ])
      if (tagsRes.ok) historyTags.value = await tagsRes.json()
      if (statsRes.ok) historyStats.value = await statsRes.json()
    } else {
      showError('批量删除失败，请稍后重试')
    }
  } catch {
    showError('批量删除失败，请稍后重试')
  } finally {
    batchDeleting.value = false
  }
}

function formatDuration(seconds) {
  if (!seconds) return ''
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m} 分钟`
}

function formatNotesChars(chars) {
  if (!chars) return '0'
  if (chars >= 10000) return (chars / 10000).toFixed(1) + '万'
  return chars.toLocaleString()
}

function toggleGroup(groupId) {
  expandedGroups.value[groupId] = !expandedGroups.value[groupId]
}

// 组件挂载时自动加载数据
fetchHistoryPage()
</script>

<template>
  <section class="history-page">
    <ConfirmDialog
      :visible="Boolean(confirmation)"
      :title="confirmation?.title"
      :message="confirmation?.message || ''"
      confirm-label="确认"
      danger
      @confirm="closeConfirmation(true)"
      @close="closeConfirmation(false)"
    />
    <Transition name="error-toast">
      <div v-if="errorMessage" class="error-toast" @click="errorMessage = ''">
        <svg viewBox="0 0 20 20" fill="currentColor" class="error-toast-icon"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/></svg>
        <span>{{ errorMessage }}</span>
      </div>
    </Transition>
    <div class="history-page-container">
      <!-- 统计仪表盘 -->
      <div v-if="historyStats" class="stats-dashboard">
        <div class="stat-card">
          <div class="stat-value">{{ historyStats.total_videos }}</div>
          <div class="stat-label">学习视频</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ formatNotesChars(historyStats.total_notes_chars) }}</div>
          <div class="stat-label">笔记字数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ formatDuration(historyStats.avg_duration_seconds) }}</div>
          <div class="stat-label">平均时长</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ Object.keys(historyStats.platform_distribution || {}).length }}</div>
          <div class="stat-label">覆盖平台</div>
        </div>
      </div>

      <!-- 搜索栏 -->
      <div class="history-search-bar">
        <div class="search-input-wrapper">
          <svg class="search-icon" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd"/></svg>
          <input
            v-model="historySearchQuery"
            class="search-input"
            aria-label="搜索学习历史"
            placeholder="搜索标题或摘要..."
            @keyup.enter="handleHistorySearch"
          />
        </div>
        <div class="search-controls">
          <select class="sort-select" :value="historySort" @change="setHistorySort($event.target.value)">
            <option value="newest">最新</option>
            <option value="oldest">最早</option>
          </select>
          <select class="sort-select" :value="historyPlatform" @change="setHistoryPlatform($event.target.value)">
            <option value="">全部平台</option>
            <option value="bilibili">B站</option>
            <option value="youtube">YouTube</option>
            <option value="douyin">抖音</option>
            <option value="tiktok">TikTok</option>
            <option value="xiaohongshu">小红书</option>
          </select>
          <button
            class="search-mode-btn"
            :class="{ active: selectionMode }"
            @click="toggleSelectionMode"
            title="选择模式"
          >
            <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16"><path d="M10 2a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V3a1 1 0 011-1z"/></svg>
            选择
          </button>
        </div>
      </div>

      <!-- 标签过滤栏 -->
      <div v-if="historyTags.length" class="tag-filter-bar">
        <button
          class="tag-btn"
          :class="{ active: !historyActiveTag }"
          @click="setHistoryTag('')"
        >全部</button>
        <button
          v-for="tag in historyTags.slice(0, 20)"
          :key="tag.id"
          class="tag-btn"
          :class="{ active: historyActiveTag === tag.name }"
          @click="setHistoryTag(tag.name)"
        >{{ tag.name }} <span class="tag-count">{{ tag.count }}</span></button>
      </div>

      <!-- 历史卡片列表 -->
      <div class="history-card-list">
        <div class="history-list-header">
          <div class="history-list-left">
            <label v-if="selectionMode" class="select-all-label">
              <input
                type="checkbox"
                :checked="historyItems.length > 0 && historyItems.every(item => isItemSelected(item))"
                @change="toggleSelectAll"
              />
              全选
            </label>
            <span class="history-count">共 {{ historyTotal }} 条记录</span>
            <span v-if="selectionMode && selectedIds.size > 0" class="selected-count">
              已选 {{ selectedIds.size }} 条
            </span>
          </div>
          <button
            v-if="selectionMode && selectedIds.size > 0"
            class="btn-batch-delete"
            @click="batchDeleteSelected"
            :disabled="batchDeleting"
          >
            <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14"><path fill-rule="evenodd" d="M8.75 2.5A1.75 1.75 0 006 4.25H3.75a.75.75 0 000 1.5h.372l.94 10.838A2 2 0 007.045 18.5h5.91a2 2 0 001.984-1.912l.94-10.838h.371a.75.75 0 000-1.5H14A1.75 1.75 0 0011.25 2.5h-2.5zm3.098 3.5H8.152l.912 10.5h1.872l.912-10.5z" clip-rule="evenodd"/></svg>
            {{ batchDeleting ? '删除中...' : `删除选中 (${selectedIds.size})` }}
          </button>
        </div>
        <div v-if="historyLoading" class="history-loading">
          <div class="loading-spinner"></div>
          <span>加载中...</span>
        </div>
        <div v-else-if="!historyItems.length" class="history-empty">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="empty-icon"><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m5.231 13.481L15 17.25m-4.5-15H5.625c-.621 0-1.125.504-1.125 1.125v16.5c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9zm3.75 11.625a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"/></svg>
          <span>暂无学习记录</span>
          <span class="empty-hint">使用 AI 总结视频后，记录会自动保存到这里</span>
        </div>
        <div v-else class="history-cards">
          <div v-for="item in historyItems" :key="item.id" class="history-page-card" :class="{ 'hp-card-selected': selectionMode && isItemSelected(item), 'hp-card-transcribing': isActiveItem(item) }">
            <div v-if="selectionMode" class="hp-card-checkbox" @click.stop="toggleSelectItem(item)">
              <input type="checkbox" :checked="isItemSelected(item)" />
            </div>
            <div class="hp-card-header">
              <h3 class="hp-card-heading"><button type="button" class="hp-card-title" @click="selectHistory(item)">{{ item.video_title || '未知标题' }}</button></h3>
              <span v-if="item.platform" class="hp-platform-tag">{{ item.platform }}</span>
            </div>
            <!-- 转录状态 -->
            <button v-if="isActiveItem(item)" type="button"
                 class="hp-transcribing-badge" @click.stop="toggleTaskDetail(item)" :aria-expanded="expandedTaskItem === item.url_hash">
              <template v-if="getTaskForUrl(item.url_hash)">
                <span class="hp-pulse-dot"></span>
                <span>{{ taskStageLabel(getTaskForUrl(item.url_hash), item) }}</span>
                <span class="hp-time-remaining">
                  · {{ formatRemaining(getTaskForUrl(item.url_hash)) }}
                </span>
                <span class="hp-expand-hint">{{ expandedTaskItem === item.url_hash ? '▲' : '▼' }}</span>
              </template>
              <template v-else>
                <span>正在同步任务状态</span>
              </template>
            </button>
            <!-- 转录任务详情面板 -->
            <div v-if="isActiveItem(item) && expandedTaskItem === item.url_hash" class="hp-task-detail">
              <div class="hp-task-info">
                <span v-if="getTaskForUrl(item.url_hash)?.status === 'queued'">{{ formatRemaining(getTaskForUrl(item.url_hash)) }}</span>
                <span v-else-if="getTaskForUrl(item.url_hash)">已处理 {{ getElapsedSeconds(getTaskForUrl(item.url_hash)) }} 秒</span>
                <span v-if="getTaskForUrl(item.url_hash)?.progress">· {{ Math.round(getTaskForUrl(item.url_hash).progress) }}%</span>
                <span v-if="getTaskForUrl(item.url_hash)?.message">· {{ getTaskForUrl(item.url_hash).message }}</span>
              </div>
              <div class="hp-task-actions">
                <button class="hp-btn-cancel" @click.stop="cancelTask(getTaskForUrl(item.url_hash)?.task_id)" :disabled="cancelingTaskId === getTaskForUrl(item.url_hash)?.task_id">
                  {{ cancelingTaskId === getTaskForUrl(item.url_hash)?.task_id ? '取消中...' : '停止转录' }}
                </button>
                <button class="hp-btn-delete-task" @click.stop="deleteTranscribingItem(item)">
                  删除记录
                </button>
              </div>
            </div>
            <div v-if="item.status === 'failed'" class="hp-failed-badge">
              <span>转录失败</span>
            </div>
            <!-- 多P标识 -->
            <button v-if="item.is_multipart" type="button" class="hp-multipart-badge" @click="toggleGroup(item.id)" :aria-expanded="Boolean(expandedGroups[item.id])">
              <svg :class="['hp-expand-icon', { expanded: expandedGroups[item.id] }]" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>
              已学习 {{ item.total_parts ? `${item.parts_count}/${item.total_parts}` : item.parts_count }}P · {{ expandedGroups[item.id] ? '点击关闭' : '点击展开' }}
            </button>
            <!-- 多P分P列表 -->
            <div v-if="item.is_multipart && expandedGroups[item.id]" class="hp-parts-list">
              <button v-for="part in item.parts" :key="part.id" type="button" class="hp-part-item" @click="selectHistory(part)">
                <span class="hp-part-index">P{{ part.part_index ?? '?' }}</span>
                <span class="hp-part-title">{{ part.part_title || part.part_info || '未知分P' }}</span>
                <span v-if="part.part_duration" class="hp-part-time">{{ formatDuration(part.part_duration) }}</span>
              </button>
            </div>
            <p v-if="!item.is_multipart && item.summary_preview" class="hp-card-summary">{{ item.summary_preview }}</p>
            <div class="hp-card-footer">
              <div class="hp-card-tags">
                <span v-for="t in (item.tags || []).slice(0, 3)" :key="t" class="hp-tag">{{ t }}</span>
              </div>
              <div class="hp-card-meta">
                <span class="hp-card-time">{{ item.created_at?.slice(0, 10) }}</span>
                <button class="hp-action-btn" @click="toggleFavorite(item)" :title="item.is_favorite ? '取消收藏' : '收藏'" :aria-label="item.is_favorite ? '取消收藏' : '收藏'">
                  <svg viewBox="0 0 20 20" :fill="item.is_favorite ? '#EC4899' : 'none'" :stroke="item.is_favorite ? '#EC4899' : 'currentColor'" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M3.172 5.172a4 4 0 015.656 0L10 6.343l1.172-1.171a4 4 0 115.656 5.656L10 17.657l-6.828-6.829a4 4 0 010-5.656z"/></svg>
                </button>
                <button class="hp-action-btn hp-delete-btn" @click="deleteHistoryItem(item)" :disabled="deletingHistoryId === item.id" title="删除" aria-label="删除历史记录">
                  <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8.75 2.5A1.75 1.75 0 006 4.25H3.75a.75.75 0 000 1.5h.372l.94 10.838A2 2 0 007.045 18.5h5.91a2 2 0 001.984-1.912l.94-10.838h.371a.75.75 0 000-1.5H14A1.75 1.75 0 0011.25 2.5h-2.5zm3.098 3.5H8.152l.912 10.5h1.872l.912-10.5z" clip-rule="evenodd"/></svg>
                </button>
              </div>
            </div>
          </div>
        </div>
        <!-- 加载更多 -->
        <div v-if="historyHasMore && !historyLoading" class="history-load-more">
          <button class="btn-load-more" @click="loadMoreHistory" :disabled="historyLoadingMore">
            <span v-if="historyLoadingMore">加载中...</span>
            <span v-else>加载更多</span>
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.error-toast {
  position: fixed;
  bottom: 2rem;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.25rem;
  background: rgba(239, 68, 68, 0.95);
  color: white;
  font-size: 0.875rem;
  border-radius: 10px;
  z-index: 9999;
  cursor: pointer;
  box-shadow: 0 4px 20px rgba(239, 68, 68, 0.3);
  max-width: 90vw;
}
.error-toast-icon { width: 18px; height: 18px; flex-shrink: 0; }
.error-toast-enter-active { animation: toast-in 0.25s ease-out; }
.error-toast-leave-active { animation: toast-out 0.2s ease-in; }
@keyframes toast-in { from { opacity: 0; transform: translateX(-50%) translateY(1rem); } to { opacity: 1; transform: translateX(-50%) translateY(0); } }
@keyframes toast-out { from { opacity: 1; transform: translateX(-50%) translateY(0); } to { opacity: 0; transform: translateX(-50%) translateY(1rem); } }

/* ── 学习历史页 ── */
.history-page {
  padding: 2rem;
  background: var(--bg-primary);
  min-height: calc(100vh - 60px);
}
.history-page-container {
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

/* 统计仪表盘 */
.stats-dashboard {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
}
.stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 1.25rem;
  text-align: center;
  backdrop-filter: blur(12px);
}
.stat-value {
  font-size: 1.75rem;
  font-weight: 700;
  background: linear-gradient(135deg, var(--accent-blue), var(--accent-cyan));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  font-family: 'Plus Jakarta Sans', sans-serif;
}
.stat-label {
  font-size: 0.8125rem;
  color: var(--text-muted);
  margin-top: 0.25rem;
}

/* 搜索栏 */
.history-search-bar {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.search-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}
.search-icon {
  position: absolute;
  left: 1rem;
  width: 18px;
  height: 18px;
  color: var(--text-muted);
  pointer-events: none;
}
.search-input {
  width: 100%;
  padding: 0.875rem 1rem 0.875rem 2.75rem;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  color: var(--text-primary);
  font-size: 0.9375rem;
  outline: none;
  transition: border-color 0.2s;
}
.search-input::placeholder { color: var(--text-muted); }
.search-input:focus { border-color: var(--accent-blue); }
.search-controls {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}
.search-mode-btn {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.5rem 0.75rem;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-muted);
  font-size: 0.8125rem;
  cursor: pointer;
  transition: all 0.2s;
}
.search-mode-btn:hover { background: rgba(255, 255, 255, 0.06); color: var(--text-secondary); }
.search-mode-btn.active {
  background: rgba(139, 92, 246, 0.15);
  border-color: rgba(139, 92, 246, 0.3);
  color: #a78bfa;
}
.sort-select {
  padding: 0.5rem 0.75rem;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 0.8125rem;
  cursor: pointer;
  outline: none;
}
.sort-select option { background: var(--bg-primary); color: var(--text-primary); }

/* 标签过滤栏 */
.tag-filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.tag-btn {
  padding: 0.375rem 0.75rem;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border);
  border-radius: 20px;
  color: var(--text-secondary);
  font-size: 0.8125rem;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s;
}
.tag-btn:hover { background: rgba(255, 255, 255, 0.06); border-color: var(--border-hover); }
.tag-btn.active {
  background: rgba(59, 130, 246, 0.15);
  border-color: rgba(59, 130, 246, 0.3);
  color: var(--accent-blue);
}
.tag-count {
  font-size: 0.6875rem;
  color: var(--text-muted);
  margin-left: 0.125rem;
}

/* 历史卡片列表 */
.history-card-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.history-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.history-count {
  font-size: 0.8125rem;
  color: var(--text-muted);
}

/* 批量选择 */
.history-list-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.select-all-label {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  color: var(--text-secondary);
  cursor: pointer;
}
.select-all-label input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: var(--accent-blue);
}
.selected-count {
  font-size: 0.8125rem;
  color: var(--accent-blue);
  font-weight: 500;
}
.btn-batch-delete {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1rem;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 8px;
  color: #FCA5A5;
  font-size: 0.8125rem;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-batch-delete:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.25);
  border-color: rgba(239, 68, 68, 0.5);
}
.btn-batch-delete:disabled { opacity: 0.5; cursor: not-allowed; }
.hp-card-checkbox {
  margin-bottom: 0.5rem;
  cursor: pointer;
}
.hp-card-checkbox input[type="checkbox"] {
  width: 18px;
  height: 18px;
  accent-color: var(--accent-blue);
  cursor: pointer;
}
.hp-card-selected {
  border-color: rgba(59, 130, 246, 0.4) !important;
  background: rgba(59, 130, 246, 0.08) !important;
}
.history-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  padding: 3rem;
  color: var(--text-muted);
}
.loading-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--border);
  border-top-color: var(--accent-blue);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
/* @keyframes spin defined globally in style.css */
.history-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  padding: 3rem;
  color: var(--text-muted);
  font-size: 0.9375rem;
}
.empty-icon { width: 48px; height: 48px; opacity: 0.3; }
.empty-hint { font-size: 0.8125rem; opacity: 0.6; }

.history-load-more {
  display: flex;
  justify-content: center;
  padding: 1.5rem 0;
}
.btn-load-more {
  padding: 0.625rem 2rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text-secondary);
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-load-more:hover:not(:disabled) {
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
  color: var(--text-primary);
}
.btn-load-more:disabled { opacity: 0.5; cursor: not-allowed; }

.history-cards {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.history-page-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 1.25rem;
  backdrop-filter: blur(12px);
  transition: all 0.2s;
}
.history-page-card:hover {
  border-color: var(--border-hover);
  background: rgba(255, 255, 255, 0.06);
}
.hp-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
}
.hp-card-title {
  appearance: none;
  padding: 0;
  border: 0;
  background: transparent;
  text-align: left;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
  cursor: pointer;
  margin: 0;
  line-height: 1.4;
}
.hp-card-heading { margin: 0; }
.hp-card-title:hover { color: var(--accent-blue); }
.hp-platform-tag {
  flex-shrink: 0;
  padding: 0.125rem 0.5rem;
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: 6px;
  font-size: 0.6875rem;
  color: var(--accent-blue);
  font-weight: 500;
}
.hp-card-summary {
  font-size: 0.8125rem;
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 0.75rem 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.hp-card-transcribing {
  border-color: rgba(245, 158, 11, 0.3);
  background: rgba(245, 158, 11, 0.04);
}
.hp-card-transcribing .hp-card-title {
  opacity: 0.7;
}
.hp-transcribing-badge {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0.75rem;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.2);
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #f59e0b;
  margin: 0.5rem 0;
  cursor: pointer;
  text-align: left;
}
.hp-pulse-dot {
  width: 6px;
  height: 6px;
  background: #f59e0b;
  border-radius: 50%;
  animation: hp-pulse 2s ease-in-out infinite;
}
@keyframes hp-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
.hp-time-remaining {
  color: var(--text-muted);
  font-weight: 400;
}
.hp-expand-hint {
  margin-left: auto;
  font-size: 0.625rem;
  opacity: 0.6;
}
.hp-task-detail {
  padding: 0.75rem;
  margin: 0.25rem 0 0.5rem;
  background: rgba(245, 158, 11, 0.06);
  border: 1px solid rgba(245, 158, 11, 0.15);
  border-radius: 8px;
}
.hp-task-info {
  font-size: 0.8rem;
  color: var(--text-muted);
  margin-bottom: 0.625rem;
}
.hp-task-actions {
  display: flex;
  gap: 0.5rem;
}
.hp-btn-cancel {
  padding: 0.375rem 0.875rem;
  font-size: 0.75rem;
  font-weight: 600;
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px;
  background: rgba(239, 68, 68, 0.08);
  color: #ef4444;
  cursor: pointer;
  transition: all 0.15s;
}
.hp-btn-cancel:hover {
  background: rgba(239, 68, 68, 0.15);
}
.hp-btn-cancel:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.hp-btn-delete-task {
  padding: 0.375rem 0.875rem;
  font-size: 0.75rem;
  font-weight: 600;
  border: 1px solid var(--border-color, rgba(255,255,255,0.1));
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}
.hp-btn-delete-task:hover {
  background: rgba(239, 68, 68, 0.08);
  color: #ef4444;
}
.hp-failed-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.625rem;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #ef4444;
  margin: 0.5rem 0;
}
.hp-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}
.hp-card-tags {
  display: flex;
  gap: 0.375rem;
  flex-wrap: wrap;
}
.hp-tag {
  padding: 0.125rem 0.5rem;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--border);
  border-radius: 12px;
  font-size: 0.6875rem;
  color: var(--text-secondary);
}
.hp-card-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}
.hp-card-time {
  font-size: 0.75rem;
  color: var(--text-muted);
}
.hp-action-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}
.hp-action-btn svg { width: 16px; height: 16px; }
.hp-action-btn:hover { background: rgba(255, 255, 255, 0.08); color: var(--text-primary); }
.hp-delete-btn:hover { background: rgba(239, 68, 68, 0.15); color: #FCA5A5; }
.hp-action-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* 多P合并 */
.hp-multipart-badge {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin: 0.5rem 0;
  padding: 0.375rem 0.625rem;
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.15);
  border-radius: 8px;
  font-size: 0.75rem;
  color: var(--accent-blue);
  cursor: pointer;
  transition: all 0.2s;
  width: fit-content;
}
.hp-multipart-badge:hover { background: rgba(59, 130, 246, 0.15); }
.hp-expand-icon {
  width: 14px;
  height: 14px;
  transition: transform 0.2s;
}
.hp-expand-icon.expanded { transform: rotate(180deg); }

.hp-parts-list {
  margin: 0.5rem 0;
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}
.hp-part-item {
  width: 100%;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.625rem 0.875rem;
  cursor: pointer;
  transition: background 0.15s;
  border-bottom: 1px solid var(--border);
}
.hp-part-item:last-child { border-bottom: none; }
.hp-part-item:hover { background: rgba(255, 255, 255, 0.04); }
.hp-part-index {
  flex-shrink: 0;
  padding: 0.125rem 0.5rem;
  background: rgba(59, 130, 246, 0.1);
  border-radius: 6px;
  font-size: 0.6875rem;
  font-weight: 600;
  color: var(--accent-blue);
  min-width: 2rem;
  text-align: center;
}
.hp-part-title {
  flex: 1;
  font-size: 0.8125rem;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hp-part-time {
  flex-shrink: 0;
  font-size: 0.6875rem;
  color: var(--text-muted);
}

/* 移动端适配 */
@media (max-width: 768px) {
  .history-page { padding: 1rem; }
  .stats-dashboard { grid-template-columns: repeat(2, 1fr); }
  .stat-value { font-size: 1.25rem; }
  .search-controls { flex-wrap: wrap; }
  .sort-select,
  .search-mode-btn,
  .btn-batch-delete,
  .btn-load-more,
  .hp-transcribing-badge,
  .hp-multipart-badge,
  .hp-part-item { min-height: 44px; }
  .hp-card-header { flex-direction: column; gap: 0.375rem; }
  .hp-card-footer { flex-direction: column; align-items: flex-start; gap: 0.5rem; }

  /* 操作按钮确保 44px 触摸目标 */
  .hp-action-btn { width: 44px; height: 44px; }
  .tag-btn { min-height: 44px; padding: 0.5rem 0.75rem; }
}
</style>
