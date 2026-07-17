<script setup>
import { computed, shallowRef, watch } from 'vue'
import { formatModelLabel } from '../../utils/modelLabel.js'

const props = defineProps({
  connection: { type: Object, required: true },
  active: { type: Object, required: true },
  pending: { type: Object, required: true },
  connectionFeedback: { type: Object, default: null },
  modelFeedback: { type: Object, required: true },
})

const emit = defineEmits(['edit', 'delete', 'refresh', 'test', 'switch', 'clear-model-feedback'])
const expanded = shallowRef(false)
const selectedModelId = shallowRef(props.connection.primary_model_id)
const isActiveConnection = computed(() => props.active.connection_id === props.connection.id)
const primaryModel = computed(() => props.connection.models.find(model => model.id === props.connection.primary_model_id) || null)
const testKey = computed(() => primaryModel.value ? `${props.connection.id}:${primaryModel.value.id}` : '')
const currentModelFeedback = computed(() => testKey.value ? props.modelFeedback[testKey.value] : null)
const isSwitching = computed(() => props.pending.switch === props.connection.id)
const isRefreshing = computed(() => Boolean(props.pending.refresh[props.connection.id]))
const isTesting = computed(() => Boolean(testKey.value && props.pending.test[testKey.value]))

const discoveryLabels = {
  available: '已发现',
  not_returned: '本次未发现',
  manual: '手动添加',
}
const testLabels = {
  passed: '测试通过',
  failed: '测试失败',
  untested: '未测试',
}

watch(() => props.connection.primary_model_id, value => {
  selectedModelId.value = value
})

watch(() => props.pending.switch, (next, previous) => {
  if (previous === props.connection.id && next !== props.connection.id) {
    selectedModelId.value = props.connection.primary_model_id
  }
})

function switchModel() {
  if (selectedModelId.value && selectedModelId.value !== props.connection.primary_model_id) {
    emit('switch', props.connection.id, selectedModelId.value)
  }
}

function toggleExpanded() {
  if (expanded.value && testKey.value) emit('clear-model-feedback', testKey.value)
  expanded.value = !expanded.value
}
</script>

<template>
  <article class="connection" :class="{ expanded, 'connection--active': isActiveConnection }">
    <header class="connection-header">
      <button type="button" class="summary" :aria-expanded="expanded" @click="toggleExpanded">
        <svg class="chevron" :class="{ rotated: expanded }" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>
        <span class="identity">
          <strong :title="connection.name">{{ connection.name }}</strong>
          <span class="format">{{ connection.api_format === 'openai' ? 'OpenAI' : 'Anthropic' }}</span>
          <span v-if="isActiveConnection" class="active-badge">使用中</span>
        </span>
        <code class="current-model" :class="{ 'current-model--active': isActiveConnection }" :title="primaryModel?.model || ''">{{ primaryModel?.model || '暂无模型' }}</code>
      </button>
      <div v-if="!connection.readonly" class="toolbar">
        <button type="button" class="icon-button" :disabled="isRefreshing" title="刷新模型" aria-label="刷新模型" @click="$emit('refresh', connection.id)">
          <svg :class="{ spinner: isRefreshing }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M20 11a8.1 8.1 0 00-15.5-2M4 4v5h5m-5 4a8.1 8.1 0 0015.5 2M20 20v-5h-5"/></svg>
        </button>
        <button type="button" class="icon-button" title="编辑连接" aria-label="编辑连接" @click="$emit('edit', connection)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M12 20h9M16.5 3.5a2.1 2.1 0 013 3L8 18l-4 1 1-4L16.5 3.5z"/></svg></button>
        <button type="button" class="icon-button danger" :disabled="pending.delete === connection.id" title="删除连接" aria-label="删除连接" @click="$emit('delete', connection)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M3 6h18M8 6V4h8v2m-9 0 1 14h8l1-14M10 10v6m4-6v6"/></svg></button>
      </div>
    </header>

    <p v-if="connectionFeedback?.action === 'refresh'" class="inline-feedback" :class="`inline-feedback--${connectionFeedback.type}`" aria-live="polite">{{ connectionFeedback.message }}</p>

    <div v-if="expanded" class="details">
      <dl>
        <div><dt>API Key</dt><dd :title="connection.api_key">{{ connection.api_key }}</dd></div>
        <div><dt>Base URL</dt><dd :title="connection.base_url">{{ connection.base_url }}</dd></div>
      </dl>

      <div v-if="primaryModel" class="model-selector">
        <label class="model-select-label">
          <span>主力模型 <svg v-if="isSwitching" class="select-spinner spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M20 11a8.1 8.1 0 00-15.5-2M4 4v5h5m-5 4a8.1 8.1 0 0015.5 2M20 20v-5h-5"/></svg></span>
          <select v-model="selectedModelId" name="primary_model" :disabled="connection.readonly || Boolean(pending.switch)" aria-label="选择主力模型" @change="switchModel">
            <option v-for="model in connection.models" :key="model.id" :value="model.id">{{ formatModelLabel(model) }}</option>
          </select>
        </label>
        <div class="status-group" aria-label="模型状态">
          <span class="model-status" :class="`model-status--discovery-${primaryModel.discovery_status}`">{{ discoveryLabels[primaryModel.discovery_status] || '未发现' }}</span>
          <span class="model-status" :class="`model-status--test-${primaryModel.test_status}`">{{ testLabels[primaryModel.test_status] || '未测试' }}</span>
        </div>
        <button type="button" class="test-button" :disabled="isTesting" @click="$emit('test', connection.id, primaryModel.id)">
          <svg :class="{ spinner: isTesting }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>{{ isTesting ? '测试中' : '测试' }}
        </button>
        <p v-if="connectionFeedback?.action === 'switch'" class="selector-feedback" :class="`selector-feedback--${connectionFeedback.type}`" aria-live="polite">{{ connectionFeedback.message }}</p>
        <div v-if="currentModelFeedback" class="test-feedback" :class="`test-feedback--${currentModelFeedback.type}`" role="status" aria-live="polite">
          <svg v-if="currentModelFeedback.type === 'success'" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M16.704 5.29a1 1 0 010 1.414l-7.2 7.2a1 1 0 01-1.414 0l-3.2-3.2a1 1 0 011.414-1.414l2.493 2.493 6.493-6.493a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
          <svg v-else viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-11a1 1 0 10-2 0v4a1 1 0 102 0V7zm-1 7a1 1 0 100 2 1 1 0 000-2z" clip-rule="evenodd"/></svg>
          <strong>{{ currentModelFeedback.type === 'success' ? '测试通过' : '测试失败' }}</strong>
          <span :title="currentModelFeedback.message">{{ currentModelFeedback.message }}</span>
        </div>
      </div>
      <p v-else class="no-model">此连接没有可用的模型目录</p>
    </div>
  </article>
</template>

<style scoped>
.connection{overflow:hidden;border:1px solid var(--border);border-radius:8px;background:rgba(15,23,42,.28);transition:border-color .18s ease}.connection:hover,.connection.expanded{border-color:var(--border-hover)}.connection--active{border-color:rgba(59,130,246,.42);box-shadow:inset 3px 0 0 var(--accent-blue)}.connection-header{display:flex;align-items:center;min-height:58px}.summary{min-width:0;flex:1;min-height:58px;display:grid;grid-template-columns:20px minmax(130px,auto) minmax(0,1fr);align-items:center;gap:10px;padding:0 8px 0 14px;border:0;background:transparent;color:inherit;text-align:left;cursor:pointer}.summary:focus-visible,.icon-button:focus-visible,.test-button:focus-visible,.model-selector select:focus-visible{outline:2px solid var(--accent-blue);outline-offset:-2px}.chevron{width:16px;color:var(--text-muted);transition:transform .18s ease}.chevron.rotated{transform:rotate(180deg)}.identity{display:flex;align-items:center;gap:8px;min-width:0}.identity strong{overflow:hidden;font-size:14px;font-weight:650;text-overflow:ellipsis;white-space:nowrap}.format,.active-badge{padding:2px 6px;border-radius:4px;font-size:10px;white-space:nowrap}.format{background:var(--bg-card-hover);color:var(--text-muted);text-transform:uppercase}.active-badge{background:rgba(34,197,94,.12);color:#86efac}.current-model{overflow:hidden;color:var(--text-muted);font:12px ui-monospace,SFMono-Regular,monospace;text-overflow:ellipsis;white-space:nowrap}.current-model--active{color:#93c5fd}.toolbar{display:flex;padding-right:8px}.icon-button{width:44px;height:44px;display:grid;place-items:center;padding:0;border:0;border-radius:6px;background:transparent;color:var(--text-muted);cursor:pointer}.icon-button:hover:not(:disabled){background:var(--bg-card-hover);color:var(--text-primary)}.icon-button.danger:hover:not(:disabled){color:#fca5a5;background:rgba(239,68,68,.1)}.icon-button:disabled,.test-button:disabled{opacity:.5;cursor:not-allowed}.icon-button svg{width:16px;height:16px}.spinner{animation:spin .8s linear infinite}.inline-feedback{margin:0;padding:7px 16px;border-top:1px solid rgba(16,185,129,.18);background:rgba(16,185,129,.07);color:#6ee7b7;font-size:11px}.inline-feedback--error{border-color:rgba(239,68,68,.2);background:rgba(239,68,68,.07);color:#fecaca}.details{border-top:1px solid var(--border)}dl{display:grid;grid-template-columns:minmax(0,.7fr) minmax(0,1.3fr);gap:16px;padding:10px 16px;margin:0;background:rgba(255,255,255,.015)}dl div{display:grid;grid-template-columns:auto minmax(0,1fr);gap:8px;min-width:0}dt{font-size:11px;color:var(--text-muted);white-space:nowrap}dd{min-width:0;margin:0;overflow:hidden;color:var(--text-secondary);font:11px ui-monospace,SFMono-Regular,monospace;text-overflow:ellipsis;white-space:nowrap}.model-selector{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:end;gap:10px;padding:12px 16px}.model-select-label{display:grid;gap:5px;min-width:0;color:var(--text-muted);font-size:11px}.model-select-label>span{display:flex;align-items:center;gap:6px}.select-spinner{width:13px;height:13px}.model-selector select{width:100%;min-width:0;height:40px;padding:0 34px 0 10px;border:1px solid var(--border-hover);border-radius:6px;background:var(--bg-card);color:var(--text-primary);font-size:12px;outline:none}.status-group{display:flex;align-items:center;gap:5px;margin-bottom:9px}.model-status{padding:2px 7px;border-radius:4px;background:rgba(148,163,184,.08);color:var(--text-muted);font-size:11px;white-space:nowrap}.model-status--discovery-available,.model-status--test-passed{background:rgba(16,185,129,.1);color:#6ee7b7}.model-status--discovery-not_returned{background:rgba(245,158,11,.1);color:#fcd34d}.model-status--discovery-manual{background:rgba(59,130,246,.1);color:#93c5fd}.model-status--test-failed{background:rgba(239,68,68,.1);color:#fca5a5}.test-button{height:40px;display:inline-flex;align-items:center;gap:6px;padding:0 12px;border:1px solid var(--border-hover);border-radius:6px;background:transparent;color:var(--text-secondary);font-size:12px;cursor:pointer}.test-button:hover:not(:disabled){background:var(--bg-card-hover);color:var(--text-primary)}.test-button svg{width:15px}.selector-feedback{grid-column:1/-1;margin:0;color:#6ee7b7;font-size:11px}.selector-feedback--error{color:#fca5a5}.test-feedback{grid-column:1/-1;display:grid;grid-template-columns:18px auto minmax(0,1fr);align-items:center;gap:7px;min-height:38px;padding:8px 10px;border:1px solid rgba(16,185,129,.24);border-radius:6px;background:rgba(16,185,129,.08);color:#6ee7b7;font-size:12px}.test-feedback svg{width:18px;height:18px}.test-feedback strong{white-space:nowrap}.test-feedback span{min-width:0;overflow:hidden;color:#a7f3d0;text-overflow:ellipsis;white-space:nowrap}.test-feedback--error{border-color:rgba(239,68,68,.24);background:rgba(239,68,68,.08);color:#fca5a5}.test-feedback--error span{color:#fecaca}.no-model{margin:0;padding:18px 16px;color:var(--text-muted);font-size:12px}@media(max-width:680px){.status-group{grid-column:1/-1;grid-row:2;margin:0}.test-button{grid-column:2;grid-row:1}.model-selector{grid-template-columns:minmax(0,1fr) auto}}@media(max-width:560px){.connection-header{align-items:flex-start}.summary{grid-template-columns:20px minmax(0,1fr);padding-top:8px;padding-bottom:8px}.identity{flex-wrap:wrap}.current-model{grid-column:2}.toolbar{padding-top:7px}.icon-button{width:40px}dl{grid-template-columns:minmax(0,1fr);gap:6px}.model-selector{padding:10px 12px}.status-group{flex-wrap:wrap}.test-button{padding:0 10px}.test-feedback{grid-template-columns:18px minmax(0,1fr)}.test-feedback span{grid-column:1/-1;white-space:normal}}@media(prefers-reduced-motion:reduce){.connection,.chevron{transition:none}.spinner{animation:none}}
</style>
