<script setup>
import { computed, shallowRef, watch } from 'vue'
import { useAdminConfig } from '../composables/useAdminConfig.js'
import BaseDialog from './BaseDialog.vue'
import ConfirmDialog from './ConfirmDialog.vue'
import ConnectionForm from './ai-config/ConnectionForm.vue'
import ConnectionList from './ai-config/ConnectionList.vue'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['close'])
const api = useAdminConfig()
const editing = shallowRef(undefined)
const deleting = shallowRef(null)
const deleteError = shallowRef('')
const discoveryResult = shallowRef(null)
const discoveryError = shallowRef('')
const formDirty = shallowRef(false)
const discardIntent = shallowRef('')

const activeConnection = computed(() => api.connections.value.find(item => item.id === api.active.connection_id))
const activeModel = computed(() => activeConnection.value?.models.find(model => model.id === api.active.model_id))

watch(() => props.visible, visible => {
  if (visible) {
    editing.value = undefined
    deleting.value = null
    formDirty.value = false
    discardIntent.value = ''
    api.clearFeedback()
    api.fetchConnections()
  } else {
    api.clearFeedback()
    discoveryResult.value = null
    discoveryError.value = ''
  }
}, { immediate: true })

function beginEdit(connection = null) {
  editing.value = connection
  discoveryResult.value = null
  discoveryError.value = ''
  formDirty.value = false
  api.clearNotification()
}

function finishEditing() {
  editing.value = undefined
  discoveryResult.value = null
  discoveryError.value = ''
  formDirty.value = false
}

function requestClose(intent = 'modal') {
  if (api.pending.save) return
  if (editing.value !== undefined && formDirty.value) {
    discardIntent.value = intent
    return
  }
  if (intent === 'form') finishEditing()
  else emit('close')
}

function confirmDiscard() {
  const intent = discardIntent.value
  discardIntent.value = ''
  if (intent === 'modal') emit('close')
  else finishEditing()
}

async function discover(payload) {
  discoveryError.value = ''
  try {
    discoveryResult.value = await api.discoverModels({
      ...payload,
      connection_id: editing.value?.id || '',
    })
  } catch (error) {
    discoveryError.value = error.message
  }
}

async function save(payload) {
  try {
    const saved = await api.saveConnection(payload, editing.value?.id)
    if (saved) finishEditing()
  } catch {
    // The composable owns the temporary operation notification.
  }
}

function beginDelete(connection) {
  deleting.value = connection
  deleteError.value = ''
}

async function confirmDelete() {
  if (!deleting.value) return
  deleteError.value = ''
  try {
    const result = await api.deleteConnection(deleting.value.id)
    if (result) deleting.value = null
  } catch (error) {
    deleteError.value = error.message
  }
}

function handleNotificationFocusOut(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) api.resumeNotification()
}
</script>

<template>
  <ConfirmDialog
    :visible="Boolean(deleting)"
    title="删除连接"
    :message="`确定删除连接「${deleting?.name || ''}」及其完整模型目录？`"
    confirm-label="删除"
    busy-label="删除中..."
    :busy="api.pending.delete === deleting?.id"
    :error="deleteError"
    danger
    @confirm="confirmDelete"
    @close="deleting = null"
  />
  <ConfirmDialog
    :visible="Boolean(discardIntent)"
    title="放弃未保存的修改？"
    message="当前连接配置尚未保存，离开后这些修改会丢失。"
    confirm-label="放弃修改"
    danger
    @confirm="confirmDiscard"
    @close="discardIntent = ''"
  />

  <BaseDialog
    :visible="visible"
    title-id="ai-settings-title"
    close-label="关闭 AI 连接配置"
    size="wide"
    panel-class="ai-settings-panel"
    :close-on-overlay="false"
    @close="requestClose('modal')"
  >
    <header class="settings-header">
      <div><h2 id="ai-settings-title">AI 连接</h2><p>管理中转站、模型目录和业务主力模型</p></div>
      <button v-if="editing === undefined" type="button" class="add-button" :disabled="api.pending.load" @click="beginEdit(null)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path stroke-linecap="round" d="M12 5v14M5 12h14"/></svg>添加连接</button>
    </header>

    <div v-if="editing === undefined && api.active.connection_id && !api.pending.load" class="active-summary" aria-live="polite">
      <span class="active-summary__label"><span class="active-dot" aria-hidden="true"></span>当前使用</span>
      <strong :title="activeConnection?.name || ''">{{ activeConnection?.name || '未知连接' }}</strong>
      <code :title="activeModel?.model || ''">{{ activeModel?.model || '未指定模型' }}</code>
    </div>

    <div
      v-if="api.notification.value"
      class="operation-notice"
      :class="`operation-notice--${api.notification.value.type}`"
      role="status"
      aria-live="polite"
      @mouseenter="api.pauseNotification"
      @mouseleave="api.resumeNotification"
      @focusin="api.pauseNotification"
      @focusout="handleNotificationFocusOut"
    >
      <span>{{ api.notification.value.message }}</span>
      <button type="button" aria-label="关闭通知" title="关闭通知" @click="api.clearNotification"><svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg></button>
    </div>

    <ConnectionForm
      v-if="editing !== undefined"
      :connection="editing"
      :pending="api.pending"
      :discovery-result="discoveryResult"
      :discovery-error="discoveryError"
      @dirty-change="formDirty = $event"
      @cancel="requestClose('form')"
      @discover="discover"
      @save="save"
    />
    <ConnectionList
      v-else
      :connections="api.connections.value"
      :active="api.active"
      :pending="api.pending"
      :load-error="api.loadError.value"
      :connection-feedback="api.connectionFeedback"
      :model-feedback="api.modelFeedback"
      @retry="api.fetchConnections"
      @edit="beginEdit"
      @delete="beginDelete"
      @refresh="api.refreshConnection"
      @test="api.testModel"
      @switch="api.switchModel"
      @clear-model-feedback="api.clearModelFeedback"
    />
  </BaseDialog>
</template>

<style scoped>
.settings-header{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:16px;padding-right:42px}.settings-header h2{margin:0;font-size:20px;letter-spacing:0}.settings-header p{margin:4px 0 0;color:var(--text-secondary);font-size:13px}.add-button{min-height:40px;display:inline-flex;align-items:center;gap:7px;padding:0 14px;border:1px solid var(--accent-blue);border-radius:6px;background:var(--accent-blue);color:white;font-size:12px;font-weight:600;cursor:pointer}.add-button:hover:not(:disabled){background:#2563eb}.add-button:disabled{opacity:.5;cursor:not-allowed}.add-button:focus-visible,.operation-notice button:focus-visible{outline:2px solid var(--accent-blue);outline-offset:2px}.add-button svg{width:15px;height:15px}.active-summary{display:grid;grid-template-columns:auto auto minmax(0,1fr);align-items:center;gap:10px;margin:0 0 12px;padding:10px 12px;border-left:3px solid var(--accent-blue);background:rgba(59,130,246,.07);font-size:12px}.active-summary__label{display:flex;align-items:center;gap:6px;color:#93c5fd}.active-dot{width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 3px rgba(34,197,94,.12)}.active-summary strong{min-width:0;overflow:hidden;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.active-summary code{min-width:0;overflow:hidden;color:#bfdbfe;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.operation-notice{min-height:40px;display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 0 12px;padding:7px 7px 7px 11px;border:1px solid rgba(16,185,129,.25);border-radius:6px;background:rgba(16,185,129,.08);color:#6ee7b7;font-size:12px}.operation-notice--error{border-color:rgba(239,68,68,.27);background:rgba(239,68,68,.08);color:#fecaca}.operation-notice span{min-width:0;overflow-wrap:anywhere}.operation-notice button{width:32px;height:32px;display:grid;place-items:center;flex:0 0 auto;padding:0;border:0;border-radius:5px;background:transparent;color:inherit;cursor:pointer}.operation-notice button:hover{background:rgba(255,255,255,.08)}.operation-notice svg{width:15px;height:15px}@media(max-width:560px){.settings-header{align-items:flex-start;flex-direction:column;padding-right:44px}.add-button{width:100%;min-height:44px;justify-content:center}.active-summary{grid-template-columns:auto minmax(0,1fr)}.active-summary code{grid-column:1/-1}}@media(prefers-reduced-motion:reduce){.active-dot{box-shadow:none}}
</style>
