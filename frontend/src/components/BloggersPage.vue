<script setup>
import { computed, onMounted, ref } from 'vue'
import { useBloggers } from '../composables/useBloggers.js'
import { thumbnailSrc } from '../utils/thumbnail.js'
import BaseDialog from './BaseDialog.vue'
import ConfirmDialog from './ConfirmDialog.vue'

const emit = defineEmits(['open-blogger'])

const {
  bloggers, bloggersLoading, bloggersError, pending, error,
  listBloggers, previewBlogger, addBlogger, updateBlogger, removeBlogger,
  getDeletionPreview, syncBlogger, cancelSync, startSyncPolling,
} = useBloggers()

// ── 添加/预览 ──
const input = ref('')
const showAdd = ref(false)
const preview = ref(null) // {profile, already_subscribed, sub}

// ── alias 行内编辑 ──
const editingId = ref(null)
const editingValue = ref('')

// ── 搜索/排序 ──
const searchQuery = ref('')
const sortBy = ref('recent')

const filteredBloggers = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  let list = bloggers.value
  if (q) {
    list = list.filter(item =>
      [item.alias, item.name, item.uid].some(value => String(value || '').toLowerCase().includes(q)))
  }
  const sorted = [...list]
  if (sortBy.value === 'followers') sorted.sort((a, b) => (b.follower_count || 0) - (a.follower_count || 0))
  else if (sortBy.value === 'catalog') sorted.sort((a, b) => (b.catalog_count || 0) - (a.catalog_count || 0))
  else if (sortBy.value === 'learned') sorted.sort((a, b) => (b.learned_count || 0) - (a.learned_count || 0))
  else sorted.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
  return sorted
})

// ── 删除预览 ──
const deletePreview = ref(null) // deletion-preview payload
const showDeleteDialog = ref(false)

// ── toast / confirm ──
const toast = ref(null)
let toastTimer = null
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

// ── 展示辅助 ──
function displayNameOf(item) {
  return item.alias || item.name || `UP ${item.uid}`
}

function syncLabel(item) {
  switch (item.sync_status) {
    case 'running': return item.sync_mode === 'deep' ? '深度同步中…' : '增量同步中…'
    case 'queued': return '同步排队中'
    case 'complete': return item.last_synced_at ? `已同步 · ${item.catalog_count ?? 0} 个投稿` : '已同步'
    case 'paused': return item.sync_error_code === 'login' ? '需配置 B 站 Cookie' : '同步已暂停'
    case 'failed': return '同步失败'
    case 'interrupted': return '同步被中断'
    case 'cancelled': return '同步已取消'
    default: return '尚未同步'
  }
}

function syncProgressText(item) {
  const page = item.sync_page || 0
  const found = item.sync_found || 0
  const added = item.sync_added || 0
  const expected = item.sync_expected
  const scanned = item.sync_mode === 'deep' && expected ? `${found}/${expected}` : `${found}`
  return `第 ${page} 页 · 已扫描 ${scanned} · 新增 ${added}`
}

function isSyncActive(item) {
  return item.sync_status === 'running' || item.sync_status === 'queued'
}

function syncTone(item) {
  if (item.sync_status === 'complete') return 'tone-ok'
  if (item.sync_status === 'failed' || item.sync_status === 'paused') return 'tone-bad'
  return 'tone-busy'
}

function anySyncActive() {
  return bloggers.value.some(isSyncActive)
}

// ── 动作 ──
function openAdd() {
  preview.value = null
  input.value = ''
  showAdd.value = true
}

async function handlePreview() {
  const value = input.value.trim()
  if (!value) return showToast('请输入 UP 主空间地址或数字 UID')
  try {
    preview.value = await previewBlogger(value)
  } catch (err) {
    preview.value = null
    showToast(error.value || err.message)
  }
}

async function handleConfirmAdd() {
  try {
    const result = await addBlogger(input.value.trim())
    showAdd.value = false
    preview.value = null
    input.value = ''
    await listBloggers()
    if (result.already_subscribed) {
      showToast('该博主已在你的列表中，已为你刷新状态', 'success')
    } else {
      showToast('已添加并开始同步投稿目录', 'success')
      ensureSyncPolling()
    }
  } catch (err) {
    showToast(error.value || err.message)
  }
}

async function handleRefreshExisting(item) {
  showAdd.value = false
  preview.value = null
  try {
    await syncBlogger(item.id, { mode: 'incremental' })
    await listBloggers()
    showToast('已开始刷新目录', 'success')
    ensureSyncPolling()
  } catch (err) {
    showToast(error.value || err.message)
  }
}

function handleGoExisting(item) {
  showAdd.value = false
  preview.value = null
  emit('open-blogger', item)
}

function startEditAlias(item) {
  editingId.value = item.id
  editingValue.value = item.alias || ''
}

async function saveAlias(item) {
  const value = editingValue.value.trim()
  editingId.value = null
  if (value === (item.alias || '')) return
  try {
    await updateBlogger(item.id, { alias: value })
    await listBloggers()
    showToast(value ? '备注已保存' : '备注已清除', 'success')
  } catch (err) {
    showToast(error.value || err.message)
  }
}

async function handleSync(item, mode = 'incremental') {
  try {
    const result = await syncBlogger(item.id, { mode })
    await listBloggers()
    showToast(result.already_running ? '同步已在进行中' : (mode === 'deep' ? '已开始深度同步' : '已开始增量同步'), 'success')
    ensureSyncPolling()
  } catch (err) {
    showToast(error.value || err.message)
  }
}

async function handleDeepSync(item) {
  if (!await requestConfirmation(
    '将重新扫描该博主的全部投稿页，耗时较长；用于补漏或刷新旧投稿信息。日常更新用「同步」即可。',
    '深度同步',
  )) return
  await handleSync(item, 'deep')
}

async function handleCancelSync(item) {
  try {
    await cancelSync(item.id)
    await listBloggers()
    showToast('已请求取消同步', 'success')
  } catch (err) {
    showToast(error.value || err.message)
  }
}

async function handleRemove(item) {
  try {
    deletePreview.value = await getDeletionPreview(item.id)
  } catch (err) {
    showToast(error.value || err.message)
    return
  }
  showDeleteDialog.value = true
}

async function confirmRemove() {
  const previewData = deletePreview.value
  showDeleteDialog.value = false
  deletePreview.value = null
  if (!previewData) return
  try {
    await removeBlogger(previewData.sub.id)
    await listBloggers()
    showToast('已退订，学习资料保留', 'success')
  } catch (err) {
    showToast(error.value || err.message || '退订失败，请稍后重试')
  }
}

function openBlogger(item) {
  emit('open-blogger', item)
}

function ensureSyncPolling() {
  startSyncPolling(anySyncActive, listBloggers)
}

onMounted(async () => {
  await listBloggers()
  ensureSyncPolling()
})
</script>

<template>
  <div class="bloggers-page">
    <div class="bloggers-container">
      <header class="bloggers-header">
        <div>
          <h1 class="bloggers-title">我的博主</h1>
          <p class="bloggers-subtitle">订阅 B 站 UP 主，浏览投稿并批量生成学习资料</p>
        </div>
        <button class="btn-primary" :disabled="pending.add" @click="openAdd">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="btn-icon">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/>
          </svg>
          添加博主
        </button>
      </header>

      <div v-if="bloggersError" class="error-banner">
        <svg viewBox="0 0 20 20" fill="currentColor" class="banner-icon">
          <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
        </svg>
        <span>{{ bloggersError }}</span>
        <button class="btn-ghost btn-ghost--sm" @click="listBloggers">重试</button>
      </div>

      <div v-if="bloggers.length" class="list-toolbar">
        <div class="search-wrap">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="search-icon">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-4.35-4.35M17 11a6 6 0 11-12 0 6 6 0 0112 0z"/>
          </svg>
          <input v-model="searchQuery" class="search-input" type="search" placeholder="搜索备注名 / 昵称 / UID…" />
        </div>
        <select v-model="sortBy" class="sort-select" aria-label="排序">
          <option value="recent">最近添加</option>
          <option value="followers">粉丝数</option>
          <option value="catalog">投稿数</option>
          <option value="learned">已整理数</option>
        </select>
      </div>

      <div v-if="bloggersLoading && !bloggers.length" class="bloggers-empty">
        <div class="loading-spinner"></div>
        <p class="empty-hint">正在加载博主列表…</p>
      </div>

      <div v-else-if="!bloggers.length && !bloggersError" class="bloggers-empty">
        <div class="empty-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m6-1.13a4 4 0 10-4-4 4 4 0 004 4zm6-4a4 4 0 11-4-4"/>
          </svg>
        </div>
        <p class="empty-hint">还没有订阅任何博主</p>
        <p class="empty-sub">点「添加博主」，粘贴 UP 主空间链接或数字 UID</p>
      </div>

      <div v-else-if="!filteredBloggers.length" class="bloggers-empty">
        <p class="empty-hint">没有匹配「{{ searchQuery }}」的博主</p>
      </div>

      <div v-else class="blogger-grid">
        <article v-for="item in filteredBloggers" :key="item.id" class="blogger-card" @click="openBlogger(item)">
          <img
            v-if="item.avatar"
            :src="thumbnailSrc(item.avatar)"
            alt=""
            class="blogger-avatar"
            referrerpolicy="no-referrer"
          />
          <div v-else class="blogger-avatar blogger-avatar--placeholder">{{ displayNameOf(item).slice(0, 1) }}</div>
          <div class="blogger-meta">
            <div class="blogger-name-row">
              <template v-if="editingId === item.id">
                <input
                  v-model="editingValue"
                  class="alias-input"
                  maxlength="64"
                  placeholder="备注名（留空显示昵称）"
                  @click.stop
                  @keyup.enter="saveAlias(item)"
                  @keyup.esc="editingId = null"
                />
                <button class="btn-icon-only" title="保存" @click.stop="saveAlias(item)">✓</button>
                <button class="btn-icon-only" title="取消" @click.stop="editingId = null">✗</button>
              </template>
              <template v-else>
                <h2 class="blogger-name">{{ displayNameOf(item) }}</h2>
                <button class="btn-icon-only" title="编辑备注名" @click.stop="startEditAlias(item)">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="btn-icon">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                  </svg>
                </button>
              </template>
            </div>
            <p class="blogger-stats">
              <span class="stat-chip">{{ item.follower_count || 0 }} 粉丝</span>
              <span class="stat-chip">{{ item.catalog_count ?? 0 }} 投稿</span>
              <span class="stat-chip">有字幕 {{ item.subtitle_count ?? 0 }}</span>
              <span class="stat-chip stat-chip--learned">已整理 {{ item.organized_count ?? item.learned_count ?? 0 }}</span>
            </p>
            <p class="blogger-sync" :class="syncTone(item)">
              <span class="sync-dot"></span>{{ syncLabel(item) }}
            </p>
            <p v-if="isSyncActive(item)" class="sync-progress">{{ syncProgressText(item) }}</p>
          </div>
          <div class="blogger-actions" @click.stop>
            <template v-if="isSyncActive(item)">
              <button class="btn-ghost btn-ghost--sm" :disabled="pending.cancelSync === item.id" @click="handleCancelSync(item)">取消同步</button>
            </template>
            <template v-else>
              <button class="btn-ghost btn-ghost--sm" :disabled="pending.sync === item.id" title="增量同步（日常更新，速度快）"
                      @click="handleSync(item, 'incremental')">同步</button>
              <button class="btn-ghost btn-ghost--sm" :disabled="pending.sync === item.id" title="全量重扫所有投稿页"
                      @click="handleDeepSync(item)">深度同步</button>
            </template>
            <button class="btn-ghost btn-ghost--sm btn-ghost--danger" :disabled="pending.remove === item.id" title="退订"
                    @click="handleRemove(item)">退订</button>
          </div>
        </article>
      </div>
    </div>

    <!-- 添加/预览弹窗 -->
    <BaseDialog :visible="showAdd" title-id="add-blogger-title" @close="showAdd = false">
      <h2 id="add-blogger-title" class="dialog-title">添加 B 站博主</h2>
      <form class="add-form" @submit.prevent="preview ? handleConfirmAdd() : handlePreview()">
        <label class="add-label" for="blogger-input">UP 主空间地址或数字 UID</label>
        <input
          id="blogger-input"
          v-model="input"
          class="add-input"
          type="text"
          placeholder="例如 https://space.bilibili.com/475210 或 475210"
          autocomplete="off"
          :disabled="!!preview"
        />
        <p class="add-hint">粘贴分享文本也可以；不支持昵称搜索</p>

        <div v-if="preview" class="preview-card">
          <img
            v-if="preview.profile.avatar"
            :src="thumbnailSrc(preview.profile.avatar)"
            alt=""
            class="preview-avatar"
            referrerpolicy="no-referrer"
          />
          <div v-else class="preview-avatar preview-avatar--placeholder">{{ (preview.profile.name || 'U').slice(0, 1) }}</div>
          <div class="preview-meta">
            <p class="preview-name">{{ preview.profile.name }}</p>
            <p class="preview-sub">UID {{ preview.profile.uid }} · {{ preview.profile.follower_count || 0 }} 粉丝</p>
          </div>
          <span v-if="preview.already_subscribed" class="chip chip--ok">已订阅</span>
        </div>

        <div class="add-actions">
          <button type="button" class="btn-ghost" @click="preview ? (preview = null) : (showAdd = false)">
            {{ preview ? '重新输入' : '取消' }}
          </button>
          <template v-if="preview && preview.already_subscribed">
            <button type="button" class="btn-ghost" @click="handleRefreshExisting(preview.sub)">刷新目录</button>
            <button type="button" class="btn-primary" @click="handleGoExisting(preview.sub)">去详情页</button>
          </template>
          <button v-else type="submit" class="btn-primary" :disabled="pending.preview || pending.add">
            <template v-if="!preview">{{ pending.preview ? '解析中…' : '预览' }}</template>
            <template v-else>{{ pending.add ? '订阅中…' : '确认订阅' }}</template>
          </button>
        </div>
      </form>
    </BaseDialog>

    <!-- 删除预览弹窗 -->
    <BaseDialog :visible="showDeleteDialog" title-id="delete-blogger-title" @close="showDeleteDialog = false">
      <h2 id="delete-blogger-title" class="dialog-title">退订「{{ displayNameOf(deletePreview?.sub || {}) }}」</h2>
      <div v-if="deletePreview" class="delete-preview">
        <p class="delete-line">将清理：</p>
        <ul class="delete-list">
          <li>订阅关系 × {{ deletePreview.will_remove.subscription }}</li>
          <li>投稿目录 × {{ deletePreview.will_remove.videos }}（分 P 记录 × {{ deletePreview.will_remove.pages }}）</li>
          <li>批次记录 × {{ deletePreview.will_remove.batches }}</li>
        </ul>
        <p v-if="!deletePreview.cascade" class="delete-note">
          <template v-if="deletePreview.remaining_subscribers > 0">其他订阅者仍在（{{ deletePreview.remaining_subscribers }} 人），共享目录将保留。</template>
          <template v-else>仍有进行中的同步/批次，本次只退订，共享目录稍后可再清理。</template>
        </p>
        <div class="preserve-box">
          <svg viewBox="0 0 20 20" fill="currentColor" class="preserve-icon">
            <path fill-rule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clip-rule="evenodd"/>
          </svg>
          <span>{{ deletePreview.preserved.note }}</span>
        </div>
        <p class="delete-hint">以确认时的实际结果为准。</p>
      </div>
      <div class="add-actions">
        <button class="btn-ghost" @click="showDeleteDialog = false">取消</button>
        <button class="btn-primary btn-primary--danger" @click="confirmRemove">确认退订</button>
      </div>
    </BaseDialog>

    <ConfirmDialog
      :visible="!!confirmation"
      :title="confirmation?.title || '确认操作'"
      :message="confirmation?.message || ''"
      confirm-label="确定"
      cancel-label="取消"
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
.bloggers-page {
  min-height: calc(100vh - 60px);
  background: var(--bg-primary);
  padding: 6rem 2rem 3rem;
}
.bloggers-container { max-width: 1100px; margin: 0 auto; display: flex; flex-direction: column; gap: 1.25rem; }

.bloggers-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.bloggers-title {
  font-size: 1.75rem; font-weight: 700; margin: 0;
  background: linear-gradient(135deg, var(--accent-blue), var(--accent-cyan));
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
.bloggers-subtitle { color: var(--text-muted); margin: 0.4rem 0 0; font-size: 0.9rem; }

.error-banner {
  display: flex; align-items: center; gap: 0.65rem;
  padding: 0.85rem 1.15rem; border-radius: 12px;
  background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.35);
  color: #fca5a5; font-size: 0.85rem;
}
.error-banner .banner-icon { width: 18px; height: 18px; flex-shrink: 0; color: #f87171; }
.error-banner .btn-ghost { margin-left: auto; }

.list-toolbar { display: flex; gap: 10px; align-items: center; }
.search-wrap { position: relative; flex: 1; }
.search-icon {
  position: absolute; left: 12px; top: 50%; transform: translateY(-50%);
  width: 16px; height: 16px; color: var(--text-muted); pointer-events: none;
}
.search-input {
  width: 100%; padding: 0.6rem 0.9rem 0.6rem 2.3rem;
  border: 1px solid var(--border); border-radius: 12px;
  background: var(--bg-card); color: var(--text-primary); font-size: 0.85rem;
}
.search-input:focus { outline: none; border-color: var(--accent-blue); }
.search-input::placeholder { color: var(--text-muted); }
.sort-select {
  padding: 0.6rem 0.75rem; border: 1px solid var(--border); border-radius: 12px;
  background: var(--bg-card); color: var(--text-secondary); font-size: 0.82rem;
}

.btn-primary {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 0.65rem 1.15rem; border: none; border-radius: 12px;
  background: linear-gradient(135deg, var(--accent-blue), var(--accent-cyan));
  color: #fff; font-weight: 600; font-size: 0.875rem; cursor: pointer;
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.btn-primary:hover:not(:disabled) { opacity: 0.92; transform: translateY(-1px); }
.btn-primary:disabled { opacity: 0.5; cursor: default; }
.btn-primary--danger { background: linear-gradient(135deg, #ef4444, #f97316); }
.btn-icon { width: 15px; height: 15px; }

.btn-ghost {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 0.45rem 0.85rem; border: 1px solid var(--border); border-radius: 10px;
  background: var(--bg-card); color: var(--text-secondary);
  font-size: 0.8rem; cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
}
.btn-ghost:hover:not(:disabled) { border-color: var(--border-hover); color: var(--text-primary); background: var(--bg-card-hover); }
.btn-ghost:disabled { opacity: 0.5; cursor: default; }
.btn-ghost--danger:hover:not(:disabled) { color: #f87171; border-color: rgba(248, 113, 113, 0.4); }
.btn-ghost--sm { padding: 0.35rem 0.7rem; font-size: 0.75rem; }
.btn-icon-only {
  border: none; background: none; color: var(--text-muted); cursor: pointer;
  padding: 2px; display: grid; place-items: center; border-radius: 6px;
}
.btn-icon-only:hover { color: var(--accent-cyan); background: var(--bg-card-hover); }

.bloggers-empty {
  text-align: center; padding: 4rem 1rem;
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 16px;
}
.empty-icon svg { width: 48px; height: 48px; color: var(--text-muted); opacity: 0.6; }
.empty-hint { margin: 1rem 0 0; color: var(--text-secondary); }
.empty-sub { margin: 0.4rem 0 0; color: var(--text-muted); font-size: 0.85rem; }

.loading-spinner {
  width: 28px; height: 28px; margin: 0 auto;
  border: 3px solid rgba(59, 130, 246, 0.2); border-top-color: var(--accent-blue);
  border-radius: 50%; animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.blogger-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 1rem; }
.blogger-card {
  display: flex; gap: 12px; align-items: flex-start; padding: 1.15rem;
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 16px;
  cursor: pointer; backdrop-filter: blur(12px);
  transition: border-color 0.15s ease, background 0.15s ease, transform 0.15s ease;
}
.blogger-card:hover {
  border-color: var(--border-hover); background: var(--bg-card-hover); transform: translateY(-2px);
}
.blogger-avatar {
  width: 54px; height: 54px; border-radius: 50%; object-fit: cover; flex-shrink: 0;
  border: 2px solid var(--border-hover); background: var(--bg-secondary);
}
.blogger-avatar--placeholder {
  display: grid; place-items: center; font-weight: 700; font-size: 1.25rem; color: var(--accent-cyan);
}
.blogger-meta { min-width: 0; flex: 1; }
.blogger-name-row { display: flex; align-items: center; gap: 6px; }
.blogger-name {
  font-size: 1rem; font-weight: 600; margin: 0; color: var(--text-primary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.alias-input {
  flex: 1; min-width: 0; padding: 0.3rem 0.55rem; font-size: 0.85rem;
  border: 1px solid var(--accent-blue); border-radius: 8px;
  background: rgba(255, 255, 255, 0.06); color: var(--text-primary);
}
.alias-input:focus { outline: none; }
.blogger-stats { display: flex; gap: 6px; margin: 0.45rem 0 0; flex-wrap: wrap; }
.stat-chip {
  font-size: 0.72rem; color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.06); padding: 2px 9px; border-radius: 999px;
}
.stat-chip--learned { color: #34d399; background: rgba(52, 211, 153, 0.12); }
.blogger-sync {
  display: flex; align-items: center; gap: 6px;
  margin: 0.5rem 0 0; font-size: 0.78rem;
}
.sync-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.tone-ok { color: #34d399; } .tone-ok .sync-dot { background: #34d399; }
.tone-bad { color: #f87171; } .tone-bad .sync-dot { background: #f87171; }
.tone-busy { color: var(--accent-cyan); } .tone-busy .sync-dot { background: var(--accent-cyan); animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: 0.35; } }
.sync-progress { margin: 0.35rem 0 0; font-size: 0.74rem; color: var(--text-muted); }
.blogger-actions { display: flex; flex-direction: column; gap: 6px; flex-shrink: 0; }

.dialog-title { margin: 0 0 0.75rem; font-size: 1.15rem; color: var(--text-primary); }
.add-form { display: flex; flex-direction: column; gap: 10px; min-width: 340px; }
.add-label { font-weight: 600; font-size: 0.88rem; color: var(--text-secondary); }
.add-input {
  padding: 0.7rem 0.9rem; border: 1px solid var(--border); border-radius: 12px;
  background: rgba(255, 255, 255, 0.05); color: var(--text-primary); font-size: 0.92rem;
  transition: border-color 0.15s ease;
}
.add-input:focus { outline: none; border-color: var(--accent-blue); }
.add-input::placeholder { color: var(--text-muted); }
.add-hint { margin: 0; font-size: 0.78rem; color: var(--text-muted); }
.add-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 8px; }

.preview-card {
  display: flex; align-items: center; gap: 12px;
  padding: 0.85rem 1rem; border-radius: 12px;
  background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.3);
}
.preview-avatar {
  width: 46px; height: 46px; border-radius: 50%; object-fit: cover;
  border: 2px solid var(--border-hover); background: var(--bg-secondary);
}
.preview-avatar--placeholder {
  display: grid; place-items: center; font-weight: 700; color: var(--accent-cyan);
}
.preview-meta { flex: 1; min-width: 0; }
.preview-name { margin: 0; font-weight: 600; color: var(--text-primary); }
.preview-sub { margin: 0.25rem 0 0; font-size: 0.8rem; color: var(--text-muted); }
.chip {
  font-size: 0.7rem; padding: 2px 10px; border-radius: 999px; font-weight: 500;
  color: #34d399; background: rgba(52, 211, 153, 0.12);
}

.delete-preview { display: flex; flex-direction: column; gap: 0.65rem; min-width: 340px; }
.delete-line { margin: 0; font-size: 0.85rem; color: var(--text-secondary); }
.delete-list { margin: 0; padding-left: 1.2rem; color: var(--text-secondary); font-size: 0.85rem; display: flex; flex-direction: column; gap: 4px; }
.delete-note { margin: 0; font-size: 0.8rem; color: #fbbf24; }
.preserve-box {
  display: flex; gap: 0.6rem; align-items: flex-start;
  padding: 0.85rem 1rem; border-radius: 12px;
  background: rgba(52, 211, 153, 0.1); border: 1px solid rgba(52, 211, 153, 0.3);
  font-size: 0.82rem; color: #6ee7b7;
}
.preserve-icon { width: 18px; height: 18px; flex-shrink: 0; margin-top: 1px; }
.delete-hint { margin: 0; font-size: 0.74rem; color: var(--text-muted); }

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
