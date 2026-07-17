<script setup>
import { computed, nextTick, reactive, shallowRef, useTemplateRef, watch } from 'vue'
import { formatModelLabel } from '../../utils/modelLabel.js'

const props = defineProps({
  connection: { type: Object, default: null },
  pending: { type: Object, required: true },
  discoveryResult: { type: Object, default: null },
  discoveryError: { type: String, default: '' },
})

const emit = defineEmits(['cancel', 'discover', 'save', 'dirtyChange'])
const form = reactive({
  name: '',
  api_format: 'openai',
  api_key: '',
  base_url: '',
  models_url: '',
  discovery_url: '',
  models: [],
  primary_model: '',
})
const query = shallowRef('')
const manual = shallowRef('')
const advancedOpen = shallowRef(false)
const baseline = shallowRef('')
const errors = reactive({})
let manualCounter = 0

const nameInput = useTemplateRef('nameInput')
const baseUrlInput = useTemplateRef('baseUrlInput')
const apiKeyInput = useTemplateRef('apiKeyInput')
const modelsUrlInput = useTemplateRef('modelsUrlInput')
const primarySelect = useTemplateRef('primarySelect')
const manualInput = useTemplateRef('manualInput')

function normalizedModel(model) {
  const source = model.source === 'manual' ? 'manual' : 'discovered'
  const legacyDiscovery = model.status === 'available'
    ? 'available'
    : model.status === 'not_returned' ? 'not_returned' : source === 'manual' ? 'manual' : 'not_returned'
  return {
    ...model,
    source,
    discovery_status: model.discovery_status || legacyDiscovery,
    test_status: model.test_status || 'untested',
    test_message: model.test_message || '',
    tested_at: model.tested_at || '',
  }
}

function snapshot() {
  return JSON.stringify({
    name: form.name,
    api_format: form.api_format,
    api_key: form.api_key,
    base_url: form.base_url,
    models_url: form.models_url,
    discovery_url: form.discovery_url,
    models: form.models,
    primary_model: form.primary_model,
    manual: manual.value,
  })
}

const dirtySnapshot = computed(snapshot)
const visibleModels = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return form.models
  return form.models.filter(model => model.id === form.primary_model ||
    `${model.name} ${model.model}`.toLowerCase().includes(needle))
})
const selectedModel = computed(() => form.models.find(model => model.id === form.primary_model) || null)

function clearErrors() {
  Object.keys(errors).forEach(key => delete errors[key])
}

function reset(connection) {
  const models = (connection?.models || []).map(model => normalizedModel({ ...model }))
  Object.assign(form, connection ? {
    name: connection.name,
    api_format: connection.api_format,
    api_key: '',
    base_url: connection.base_url,
    models_url: connection.models_url || '',
    discovery_url: connection.discovery_url || '',
    models,
    primary_model: connection.primary_model_id || connection.active_model || models[0]?.id || '',
  } : {
    name: '',
    api_format: 'openai',
    api_key: '',
    base_url: '',
    models_url: '',
    discovery_url: '',
    models: [],
    primary_model: '',
  })
  query.value = ''
  manual.value = ''
  advancedOpen.value = Boolean(connection?.models_url)
  clearErrors()
  baseline.value = snapshot()
  emit('dirtyChange', false)
}

watch(() => props.connection, reset, { immediate: true })
watch(dirtySnapshot, value => emit('dirtyChange', value !== baseline.value))

watch(() => props.discoveryResult, result => {
  if (!result) return
  const returned = new Map(result.models.map(model => [model.model, model]))
  const merged = form.models.map(existing => {
    const discovered = returned.get(existing.model)
    returned.delete(existing.model)
    if (discovered) {
      return { ...existing, name: discovered.name || existing.name, discovery_status: 'available' }
    }
    if (existing.source === 'manual' && existing.discovery_status === 'manual') return existing
    return { ...existing, discovery_status: 'not_returned' }
  })
  returned.forEach(model => merged.push(normalizedModel({
    id: `discovered-${model.model}`,
    name: model.name,
    model: model.model,
    source: 'discovered',
    discovery_status: 'available',
  })))
  form.base_url = result.base_url
  form.models_url = result.models_url || form.models_url
  form.discovery_url = result.discovery_url || ''
  form.models = merged
  if (!form.models.some(model => model.id === form.primary_model)) {
    form.primary_model = form.models[0]?.id || ''
  }
}, { deep: true })

function validUrl(value) {
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

async function focusFirstError(order) {
  await nextTick()
  const targets = { name: nameInput, base_url: baseUrlInput, api_key: apiKeyInput, models_url: modelsUrlInput, models: manualInput, primary_model: primarySelect }
  targets[order.find(key => errors[key])]?.value?.focus()
}

function validateConnectionFields() {
  clearErrors()
  if (!form.name.trim()) errors.name = '请填写配置名称'
  if (!form.base_url.trim()) errors.base_url = '请填写 Base URL'
  else if (!validUrl(form.base_url.trim())) errors.base_url = '请输入有效的 http(s) 地址'
  if (!form.api_key.trim() && !props.connection) errors.api_key = '请填写 API Key'
  if (form.models_url.trim() && !validUrl(form.models_url.trim())) errors.models_url = '请输入有效的模型列表 URL'
  return !Object.keys(errors).length
}

function requestDiscovery() {
  if (!validateConnectionFields()) {
    focusFirstError(['name', 'base_url', 'api_key', 'models_url'])
    return
  }
  emit('discover', {
    api_format: form.api_format,
    api_key: form.api_key,
    base_url: form.base_url,
    models_url: form.models_url,
  })
}

function addManual() {
  const modelId = manual.value.trim()
  if (!modelId) return
  const existing = form.models.find(item => item.model === modelId)
  if (existing) {
    form.primary_model = existing.id
  } else {
    const model = normalizedModel({
      id: `manual-${Date.now()}-${++manualCounter}`,
      name: modelId,
      model: modelId,
      source: 'manual',
      discovery_status: 'manual',
    })
    form.models.unshift(model)
    form.primary_model = model.id
  }
  manual.value = ''
  delete errors.models
  delete errors.primary_model
}

function submit() {
  const connectionValid = validateConnectionFields()
  if (!form.models.length) errors.models = '请先获取模型，或手动添加模型 ID'
  if (!form.models.some(model => model.id === form.primary_model)) errors.primary_model = '请选择主力模型'
  if (!connectionValid || errors.models || errors.primary_model) {
    focusFirstError(['name', 'base_url', 'api_key', 'models', 'primary_model', 'models_url'])
    return
  }
  emit('save', {
    name: form.name.trim(),
    api_format: form.api_format,
    api_key: form.api_key,
    base_url: form.base_url,
    models_url: form.models_url,
    discovery_url: form.discovery_url,
    models: form.models,
    primary_model: form.primary_model,
  })
}
</script>

<template>
  <form class="connection-form" novalidate @submit.prevent="submit">
    <div class="form-heading">
      <div><h3>{{ connection ? '编辑连接' : '添加连接' }}</h3><p>配置请求协议与该连接的主力模型</p></div>
      <button type="button" class="text-button" @click="$emit('cancel')">返回列表</button>
    </div>

    <section class="section" aria-labelledby="connection-fields-title">
      <div class="section-title"><span class="step">1</span><div><h4 id="connection-fields-title">连接信息</h4><p>兼容格式决定生成请求协议</p></div></div>
      <div class="field-grid">
        <label class="field"><span>配置名称</span><input ref="nameInput" v-model="form.name" name="connection_name" type="text" autocomplete="off" spellcheck="false" :aria-invalid="Boolean(errors.name)"><small v-if="errors.name" class="field-error">{{ errors.name }}</small></label>
        <fieldset class="field"><legend>兼容格式</legend><div class="segments"><label :class="{ active: form.api_format === 'openai' }"><input v-model="form.api_format" name="api_format" type="radio" value="openai">OpenAI</label><label :class="{ active: form.api_format === 'anthropic' }"><input v-model="form.api_format" name="api_format" type="radio" value="anthropic">Anthropic</label></div></fieldset>
        <label class="field field--wide"><span>Base URL</span><input ref="baseUrlInput" v-model="form.base_url" name="base_url" type="url" placeholder="https://gateway.example.com" autocomplete="url" spellcheck="false" :aria-invalid="Boolean(errors.base_url)"><small v-if="errors.base_url" class="field-error">{{ errors.base_url }}</small><small v-else>资源路径会自动规范化</small></label>
        <label class="field field--wide"><span>API Key</span><input ref="apiKeyInput" v-model="form.api_key" name="api_key" type="password" :placeholder="connection ? '留空则保留当前密钥' : 'sk-...'" autocomplete="new-password" spellcheck="false" :aria-invalid="Boolean(errors.api_key)"><small v-if="errors.api_key" class="field-error">{{ errors.api_key }}</small></label>
      </div>
      <button type="button" class="advanced-toggle" :aria-expanded="advancedOpen" @click="advancedOpen = !advancedOpen"><svg :class="{ rotated: advancedOpen }" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>高级设置</button>
      <label v-if="advancedOpen" class="field advanced-field"><span>模型列表 URL</span><input ref="modelsUrlInput" v-model="form.models_url" name="models_url" type="url" placeholder="留空自动探测" autocomplete="url" spellcheck="false" :aria-invalid="Boolean(errors.models_url)"><small v-if="errors.models_url" class="field-error">{{ errors.models_url }}</small><small v-else>仅在中转站使用特殊列表路径时填写</small></label>
      <div class="discover-row"><button type="button" class="secondary-button" :disabled="pending.discover" @click="requestDiscovery"><svg :class="{ spinner: pending.discover }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M20 11a8.1 8.1 0 00-15.5-2M4 4v5h5m-5 4a8.1 8.1 0 0015.5 2M20 20v-5h-5"/></svg>{{ pending.discover ? '正在获取...' : form.models.length ? '重新获取模型' : '获取模型' }}</button><span v-if="form.discovery_url" class="discovery-hint" :title="form.discovery_url">已通过 {{ form.discovery_url }} 获取</span></div>
      <p v-if="discoveryError" class="feedback feedback--error" role="alert">{{ discoveryError }} <button type="button" @click="requestDiscovery">重试</button></p>
    </section>

    <section class="section" aria-labelledby="model-picker-title">
      <div class="section-title"><span class="step">2</span><div><h4 id="model-picker-title">主力模型</h4><p>目录共 {{ form.models.length }} 个模型</p></div></div>
      <div class="model-tools">
        <label class="search"><span class="sr-only">搜索模型</span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input v-model="query" name="model_search" type="search" placeholder="搜索模型" autocomplete="off" spellcheck="false"></label>
        <div class="manual"><label class="sr-only" for="manual-model-id">手动输入模型 ID</label><input id="manual-model-id" ref="manualInput" v-model="manual" name="manual_model" type="search" placeholder="手动输入模型 ID" autocomplete="off" spellcheck="false" @keydown.enter.prevent="addManual"><button type="button" @click="addManual">添加</button></div>
      </div>
      <label v-if="form.models.length" class="primary-picker"><span>选择模型</span><select ref="primarySelect" v-model="form.primary_model" name="primary_model" autocomplete="off" :aria-invalid="Boolean(errors.primary_model)"><option v-for="model in visibleModels" :key="model.id || model.model" :value="model.id">{{ formatModelLabel(model) }}</option></select></label>
      <div v-else class="picker-empty">获取模型，或手动添加模型 ID</div>
      <div v-if="selectedModel" class="selected-model" aria-live="polite"><code :title="selectedModel.model">{{ selectedModel.model }}</code><span>{{ selectedModel.discovery_status === 'available' ? '已发现' : selectedModel.discovery_status === 'not_returned' ? '本次未发现' : '手动添加' }}</span><span>{{ selectedModel.test_status === 'passed' ? '测试通过' : selectedModel.test_status === 'failed' ? '测试失败' : '未测试' }}</span></div>
      <p v-if="errors.models || errors.primary_model" class="feedback feedback--error" role="alert">{{ errors.models || errors.primary_model }}</p>
    </section>

    <div class="validation-live" aria-live="assertive">{{ Object.values(errors)[0] || '' }}</div>
    <footer class="form-footer"><button type="button" class="ghost-button" @click="$emit('cancel')">取消</button><button type="submit" class="primary-button" :disabled="pending.save">{{ pending.save ? '保存中...' : '保存连接' }}</button></footer>
  </form>
</template>

<style scoped>
.connection-form{display:grid;gap:4px}.form-heading,.section-title,.discover-row,.form-footer{display:flex;align-items:center;justify-content:space-between;gap:12px}.form-heading{padding-bottom:12px}.form-heading h3{margin:0;font-size:16px;letter-spacing:0}.form-heading p,.section-title p{margin:3px 0 0;color:var(--text-muted);font-size:12px}.text-button,.advanced-toggle{border:0;background:transparent;color:var(--text-secondary);font-size:12px;cursor:pointer}.text-button:hover,.advanced-toggle:hover{color:var(--text-primary)}.section{padding:16px 0;border:0;border-top:1px solid var(--border)}.section-title{justify-content:flex-start;margin-bottom:14px}.section-title h4{margin:0;font-size:13px;letter-spacing:0}.step{width:24px;height:24px;display:grid;place-items:center;flex:0 0 auto;border-radius:50%;background:rgba(59,130,246,.14);color:#93c5fd;font-size:12px;font-weight:700}.field-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.field{display:grid;gap:5px;margin:0;padding:0;border:0;color:var(--text-secondary);font-size:12px}.field--wide{grid-column:1/-1}.field small{color:var(--text-muted);font-size:11px}.field .field-error{color:#fca5a5}.field input,.search input,.manual input,.primary-picker select{width:100%;min-height:40px;padding:0 10px;border:1px solid var(--border-hover);border-radius:6px;background:rgba(15,23,42,.65);color:var(--text-primary);font-size:13px;outline:none}.field input:focus-visible,.search:focus-within,.manual:focus-within,.primary-picker select:focus-visible{border-color:var(--accent-blue);box-shadow:0 0 0 2px rgba(59,130,246,.16)}.field input[aria-invalid=true],.primary-picker select[aria-invalid=true]{border-color:rgba(239,68,68,.65)}.segments{display:grid;grid-template-columns:1fr 1fr}.segments label{min-height:40px;display:flex;align-items:center;justify-content:center;gap:7px;border:1px solid var(--border-hover);color:var(--text-secondary);font-size:12px;cursor:pointer}.segments label:first-child{border-radius:6px 0 0 6px}.segments label:last-child{margin-left:-1px;border-radius:0 6px 6px 0}.segments label.active{position:relative;border-color:var(--accent-blue);background:rgba(59,130,246,.1);color:#bfdbfe}.segments input{position:absolute;opacity:0}.segments label:focus-within{outline:2px solid var(--accent-blue);outline-offset:2px}.advanced-toggle{display:flex;align-items:center;gap:5px;margin-top:10px;padding:7px 0}.advanced-toggle svg{width:14px;transition:transform .18s}.advanced-toggle svg.rotated{transform:rotate(180deg)}.advanced-field{margin-top:4px}.discover-row{justify-content:flex-start;margin-top:10px}.secondary-button,.primary-button,.ghost-button{min-height:40px;display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:0 14px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer}.secondary-button{border:1px solid var(--border-hover);background:var(--bg-card);color:var(--text-primary)}.secondary-button:hover:not(:disabled),.ghost-button:hover:not(:disabled){background:var(--bg-card-hover)}.secondary-button svg{width:15px}.discovery-hint{min-width:0;overflow:hidden;color:var(--text-muted);font:11px ui-monospace,SFMono-Regular,monospace;text-overflow:ellipsis;white-space:nowrap}.model-tools{display:grid;grid-template-columns:1fr 1fr;gap:8px}.search{min-height:40px;display:flex;align-items:center;border:1px solid var(--border-hover);border-radius:6px;background:rgba(15,23,42,.65)}.search svg{width:15px;margin-left:10px;color:var(--text-muted)}.search input{min-width:0;border:0;background:transparent;box-shadow:none!important}.manual{display:grid;grid-template-columns:1fr auto}.manual input{border-radius:6px 0 0 6px}.manual button{min-width:64px;border:1px solid var(--border-hover);border-left:0;border-radius:0 6px 6px 0;background:var(--bg-card);color:var(--text-secondary);font-size:12px;cursor:pointer}.manual button:hover{background:var(--bg-card-hover);color:var(--text-primary)}.primary-picker{display:grid;gap:5px;margin-top:10px;color:var(--text-secondary);font-size:12px}.primary-picker select{height:44px}.picker-empty{min-height:76px;display:grid;place-items:center;margin-top:10px;border:1px dashed var(--border-hover);border-radius:6px;color:var(--text-muted);font-size:12px}.selected-model{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:6px;margin-top:8px}.selected-model code{min-width:0;overflow:hidden;color:#bfdbfe;font-size:11px;text-overflow:ellipsis;white-space:nowrap}.selected-model span{padding:2px 6px;border-radius:4px;background:rgba(148,163,184,.08);color:var(--text-muted);font-size:10px;white-space:nowrap}.feedback{margin:10px 0 0;padding:8px 10px;border-radius:6px;font-size:12px}.feedback--error{border:1px solid rgba(239,68,68,.22);background:rgba(239,68,68,.08);color:#fca5a5}.feedback button{margin-left:6px;border:0;background:transparent;color:#fecaca;text-decoration:underline;cursor:pointer}.validation-live{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}.form-footer{justify-content:flex-end;padding-top:12px;border-top:1px solid var(--border)}.ghost-button{border:1px solid var(--border-hover);background:transparent;color:var(--text-secondary)}.primary-button{min-width:104px;border:1px solid var(--accent-blue);background:var(--accent-blue);color:white}.primary-button:hover:not(:disabled){background:#2563eb}.primary-button:disabled,.secondary-button:disabled{opacity:.5;cursor:not-allowed}.text-button:focus-visible,.advanced-toggle:focus-visible,.secondary-button:focus-visible,.ghost-button:focus-visible,.primary-button:focus-visible,.manual button:focus-visible{outline:2px solid var(--accent-blue);outline-offset:2px}.spinner{animation:spin .8s linear infinite}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}@media(max-width:560px){.section{padding:14px 0}.field-grid,.model-tools{grid-template-columns:1fr}.field--wide{grid-column:auto}.form-heading{align-items:flex-start}.discovery-hint{display:none}.field input,.search input,.manual input,.primary-picker select{min-height:44px;font-size:16px}.form-footer{display:grid;grid-template-columns:1fr 1fr}.selected-model{grid-template-columns:minmax(0,1fr) auto}.selected-model span:last-child{grid-column:2}}@media(prefers-reduced-motion:reduce){.advanced-toggle svg{transition:none}.spinner{animation:none}}
</style>
