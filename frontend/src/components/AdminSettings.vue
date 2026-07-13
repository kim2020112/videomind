<script setup>
import { ref, watch } from 'vue'
import { useAdminConfig } from '../composables/useAdminConfig.js'
import BaseDialog from './BaseDialog.vue'
import ConfirmDialog from './ConfirmDialog.vue'

const emit = defineEmits(['close'])
const props = defineProps({ visible: Boolean })

const {
  providers, active, loading, saving, testResult,
  fetchProviders, addProvider, updateProvider, deleteProvider, testProvider,
  addModel, updateModel, deleteModel, switchModel, testConnection,
} = useAdminConfig()

// 展开状态
const expanded = ref({})

// 服务商表单
const showProviderForm = ref(false)
const editingProviderId = ref(null)
const providerForm = ref({ name: '', provider: 'deepseek', api_key: '', base_url: '' })

// 模型表单
const showModelForm = ref(false)
const editingModelProviderId = ref(null)
const editingModelId = ref(null)
const modelForm = ref({ name: '', model: '' })

const formError = ref('')
const formSuccess = ref('')
const switchSuccess = ref('')
const confirmation = ref(null)
let confirmationResolve = null

function requestConfirmation(message, title) {
  confirmation.value = { message, title }
  return new Promise(resolve => { confirmationResolve = resolve })
}

function closeConfirmation(confirmed = false) {
  confirmation.value = null
  confirmationResolve?.(confirmed)
  confirmationResolve = null
}

const providersList = [
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'openrouter', label: 'OpenRouter' },
  { value: 'mimo', label: 'MIMO' },
  { value: 'other', label: '其他' },
]

watch(() => props.visible, (val) => {
  if (val) {
    formError.value = ''
    formSuccess.value = ''
    switchSuccess.value = ''
    testResult.value = null
    showProviderForm.value = false
    showModelForm.value = false
    editingProviderId.value = null
    editingModelId.value = null
    fetchProviders()
  }
})

function isActiveModel(pid, mid) {
  return active.value.provider_id === pid && active.value.model_id === mid
}

function toggleExpand(pid) {
  expanded.value[pid] = !expanded.value[pid]
}

// ── 服务商操作 ──

function openAddProvider() {
  editingProviderId.value = null
  providerForm.value = { name: '', provider: 'deepseek', api_key: '', base_url: '' }
  formError.value = ''
  testResult.value = null
  showModelForm.value = false
  showProviderForm.value = true
}

function openEditProvider(p) {
  editingProviderId.value = p.id
  providerForm.value = { name: p.name, provider: p.provider, api_key: '', base_url: p.base_url }
  formError.value = ''
  testResult.value = null
  showModelForm.value = false
  showProviderForm.value = true
}

function closeProviderForm() {
  showProviderForm.value = false
  editingProviderId.value = null
  formError.value = ''
}

async function handleSaveProvider() {
  formError.value = ''
  formSuccess.value = ''
  try {
    if (editingProviderId.value) {
      await updateProvider(editingProviderId.value, providerForm.value)
      formSuccess.value = '已更新'
    } else {
      await addProvider(providerForm.value)
      formSuccess.value = '已添加'
    }
    setTimeout(() => { formSuccess.value = ''; closeProviderForm() }, 800)
  } catch (e) {
    formError.value = e.message
  }
}

async function handleDeleteProvider(p) {
  if (!await requestConfirmation(`确定删除服务商「${p.name}」及其所有模型？`, '删除服务商')) return
  try {
    await deleteProvider(p.id)
  } catch (e) {
    formError.value = e.message
  }
}

async function handleTestProvider(p) {
  await testProvider(p.id)
}

// ── 模型操作 ──

function openAddModel(pid) {
  editingModelProviderId.value = pid
  editingModelId.value = null
  modelForm.value = { name: '', model: '' }
  formError.value = ''
  testResult.value = null
  showProviderForm.value = false
  showModelForm.value = true
}

function openEditModel(pid, m) {
  editingModelProviderId.value = pid
  editingModelId.value = m.id
  modelForm.value = { name: m.name, model: m.model }
  formError.value = ''
  testResult.value = null
  showProviderForm.value = false
  showModelForm.value = true
}

function closeModelForm() {
  showModelForm.value = false
  editingModelProviderId.value = null
  editingModelId.value = null
  formError.value = ''
}

async function handleSaveModel() {
  formError.value = ''
  formSuccess.value = ''
  try {
    if (editingModelId.value) {
      await updateModel(editingModelProviderId.value, editingModelId.value, modelForm.value)
      formSuccess.value = '已更新'
    } else {
      await addModel(editingModelProviderId.value, modelForm.value)
      formSuccess.value = '已添加'
    }
    setTimeout(() => { formSuccess.value = ''; closeModelForm() }, 800)
  } catch (e) {
    formError.value = e.message
  }
}

async function handleDeleteModel(pid, m) {
  if (!await requestConfirmation(`确定删除模型「${m.name}」？`, '删除模型')) return
  try {
    await deleteModel(pid, m.id)
  } catch (e) {
    formError.value = e.message
  }
}

async function handleSwitch(pid, mid) {
  if (isActiveModel(pid, mid)) return
  try {
    await switchModel(pid, mid)
    const p = providers.value.find(x => x.id === pid)
    const m = p?.models.find(x => x.id === mid)
    switchSuccess.value = `已切换到 ${m?.model || mid}`
    setTimeout(() => { switchSuccess.value = '' }, 2000)
  } catch (e) {
    formError.value = e.message
  }
}

async function handleTestNewProvider() {
  await testConnection({
    api_key: providerForm.value.api_key,
    base_url: providerForm.value.base_url,
    model: 'claude-sonnet-4-20250514',
  })
}
</script>

<template>
  <ConfirmDialog
    :visible="Boolean(confirmation)"
    :title="confirmation?.title"
    :message="confirmation?.message || ''"
    confirm-label="删除"
    danger
    @confirm="closeConfirmation(true)"
    @close="closeConfirmation(false)"
  />
  <BaseDialog
    :visible="visible"
    title-id="admin-settings-title"
    close-label="关闭模型配置"
    size="wide"
    @close="$emit('close')"
  >
        <h2 id="admin-settings-title" class="modal-title">AI 模型配置</h2>
        <p class="modal-desc">管理服务商和模型，API Key 按服务商配置，模型可添加多个</p>

        <!-- 切换成功提示 -->
        <p v-if="switchSuccess" class="switch-toast">{{ switchSuccess }}</p>

        <!-- 服务商列表 -->
        <div class="provider-list">
          <div v-for="p in providers" :key="p.id" class="provider-group">
            <!-- 服务商头部 -->
            <div class="provider-header" role="button" tabindex="0" :aria-expanded="Boolean(expanded[p.id])" @click="toggleExpand(p.id)" @keydown.enter.prevent="toggleExpand(p.id)" @keydown.space.prevent="toggleExpand(p.id)">
              <div class="provider-expand">
                <svg :class="{ rotated: expanded[p.id] }" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
                </svg>
              </div>
              <div class="provider-info">
                <div class="provider-row">
                  <span class="provider-name">{{ p.name }}</span>
                  <span class="provider-tag" v-if="p.provider !== p.name.toLowerCase()">{{ p.provider }}</span>
                  <span class="provider-active-model" v-if="active.provider_id === p.id">
                    <span class="active-dot"></span>
                    {{ p.models.find(m => m.id === active.model_id)?.model || '未选择' }}
                  </span>
                  <span class="provider-count">{{ p.models.length }} 个模型</span>
                </div>
              </div>
              <div class="provider-actions" @click.stop>
                <button class="btn-icon" title="测试连接" aria-label="测试服务商连接" @click="handleTestProvider(p)">
                  <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clip-rule="evenodd"/></svg>
                </button>
                <button class="btn-icon" title="编辑" aria-label="编辑服务商" @click="openEditProvider(p)">
                  <svg viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
                </button>
                <button class="btn-icon btn-icon-danger" title="删除" aria-label="删除服务商" @click="handleDeleteProvider(p)">
                  <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
                </button>
              </div>
            </div>

            <!-- 模型列表（展开时显示） -->
            <div v-if="expanded[p.id]" class="model-list">
              <div class="provider-detail">
                <div class="detail-item">
                  <span class="detail-label">Key</span>
                  <span class="detail-value">{{ p.api_key }}</span>
                </div>
                <div class="detail-item">
                  <span class="detail-label">URL</span>
                  <span class="detail-value detail-url">{{ p.base_url }}</span>
                </div>
              </div>
              <div
                v-for="m in p.models"
                :key="m.id"
                class="model-item"
                :class="{ active: isActiveModel(p.id, m.id) }"
                role="button"
                tabindex="0"
                @click="handleSwitch(p.id, m.id)"
                @keydown.enter.prevent="handleSwitch(p.id, m.id)"
                @keydown.space.prevent="handleSwitch(p.id, m.id)"
              >
                <div class="model-info">
                  <span class="model-name">{{ m.name }}</span>
                  <span class="model-id">{{ m.model }}</span>
                </div>
                <span class="model-active-badge" v-if="isActiveModel(p.id, m.id)">当前</span>
                <div class="model-actions" @click.stop>
                  <button class="btn-icon" title="编辑" aria-label="编辑模型" @click="openEditModel(p.id, m)">
                    <svg viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
                  </button>
                  <button class="btn-icon btn-icon-danger" title="删除" aria-label="删除模型" @click="handleDeleteModel(p.id, m)">
                    <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
                  </button>
                </div>
              </div>

              <div v-if="p.models.length === 0" class="model-empty">
                还没有模型，点击下方添加
              </div>

              <button class="btn-add-model" @click="openAddModel(p.id)">
                <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
                添加模型
              </button>
            </div>
          </div>

          <div v-if="providers.length === 0 && !loading" class="provider-empty">
            还没有配置任何服务商，点击下方添加
          </div>
        </div>

        <!-- 添加服务商按钮 -->
        <button v-if="!showProviderForm && !showModelForm" class="btn-add-provider" @click="openAddProvider">
          <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
          添加服务商
        </button>

        <!-- 服务商表单 -->
        <div v-if="showProviderForm" class="form-panel">
          <div class="form-panel-header">
            <span>{{ editingProviderId ? '编辑服务商' : '添加服务商' }}</span>
            <button class="btn-icon" aria-label="关闭服务商表单" @click="closeProviderForm">
              <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
            </button>
          </div>

          <form @submit.prevent="handleSaveProvider" class="modal-form">
            <div class="form-row">
              <div class="form-group">
                <label>名称</label>
                <input v-model="providerForm.name" type="text" placeholder="DeepSeek" />
              </div>
              <div class="form-group">
                <label>服务商</label>
                <select v-model="providerForm.provider" class="form-select">
                  <option v-for="p in providersList" :key="p.value" :value="p.value">{{ p.label }}</option>
                </select>
              </div>
            </div>

            <div class="form-group">
              <label>API Key</label>
              <input v-model="providerForm.api_key" type="password" :placeholder="editingProviderId ? '留空则保持不变' : 'sk-...'" autocomplete="off" />
            </div>

            <div class="form-group">
              <label>Base URL</label>
              <input v-model="providerForm.base_url" type="text" placeholder="https://api.deepseek.com/anthropic" />
            </div>

            <p v-if="formError" class="form-error">{{ formError }}</p>
            <p v-if="formSuccess" class="form-success">{{ formSuccess }}</p>

            <div v-if="testResult" class="test-result" :class="testResult.success ? 'test-success' : 'test-fail'">
              <svg v-if="testResult.success" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>
              <svg v-else viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/></svg>
              <span>{{ testResult.message }}</span>
            </div>

            <div class="form-actions">
              <button type="button" class="btn-test" :disabled="loading" @click="handleTestNewProvider">
                {{ loading ? '测试中...' : '测试连接' }}
              </button>
              <button type="submit" class="btn-save" :disabled="saving">
                {{ saving ? '保存中...' : (editingProviderId ? '更新' : '添加') }}
              </button>
            </div>
          </form>
        </div>

        <!-- 模型表单 -->
        <div v-if="showModelForm" class="form-panel">
          <div class="form-panel-header">
            <span>{{ editingModelId ? '编辑模型' : '添加模型' }}</span>
            <button class="btn-icon" aria-label="关闭模型表单" @click="closeModelForm">
              <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
            </button>
          </div>

          <form @submit.prevent="handleSaveModel" class="modal-form">
            <div class="form-group">
              <label>模型显示名</label>
              <input v-model="modelForm.name" type="text" placeholder="V4 Flash" />
            </div>

            <div class="form-group">
              <label>模型 ID</label>
              <input v-model="modelForm.model" type="text" placeholder="deepseek-v4-flash" />
            </div>

            <p v-if="formError" class="form-error">{{ formError }}</p>
            <p v-if="formSuccess" class="form-success">{{ formSuccess }}</p>

            <div class="form-actions">
              <button type="submit" class="btn-save" :disabled="saving">
                {{ saving ? '保存中...' : (editingModelId ? '更新' : '添加') }}
              </button>
            </div>
          </form>
        </div>
  </BaseDialog>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-card {
  position: relative;
  width: 100%;
  max-width: 560px;
  background: #1e293b;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  padding: 2rem;
  margin: 1rem;
  max-height: 90vh;
  overflow-y: auto;
}

.modal-close {
  position: absolute;
  top: 1rem;
  right: 1rem;
  width: 28px;
  height: 28px;
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all 0.15s;
}
.modal-close:hover { background: rgba(255,255,255,0.1); color: #e2e8f0; }
.modal-close svg { width: 18px; height: 18px; }

.modal-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #f1f5f9;
  margin: 0 0 0.5rem;
}

.modal-desc {
  font-size: 0.8125rem;
  color: #94a3b8;
  margin: 0 0 1.25rem;
}

.switch-toast {
  font-size: 0.8125rem;
  color: #6ee7b7;
  margin: 0 0 0.75rem;
  padding: 0.5rem 0.75rem;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.2);
  border-radius: 8px;
  text-align: center;
}

/* ── 服务商列表 ── */
.provider-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.provider-group {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  overflow: hidden;
}

.provider-header {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.03);
  cursor: pointer;
  transition: background 0.15s;
}

.provider-header:hover {
  background: rgba(255, 255, 255, 0.06);
}

.provider-expand {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  color: #64748b;
  transition: transform 0.2s;
}
.provider-expand svg { width: 20px; height: 20px; }
.provider-expand svg.rotated { transform: rotate(180deg); }

.provider-info {
  flex: 1;
  min-width: 0;
}

.provider-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.125rem;
}

.provider-name {
  font-size: 0.9375rem;
  font-weight: 700;
  color: #f1f5f9;
}

.provider-tag {
  font-size: 0.625rem;
  font-weight: 600;
  color: #64748b;
  padding: 0.0625rem 0.375rem;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 3px;
  text-transform: uppercase;
}

.provider-count {
  font-size: 0.6875rem;
  color: #475569;
}

.provider-active-model {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.6875rem;
  font-weight: 600;
  color: #93c5fd;
  padding: 0.0625rem 0.5rem;
  background: rgba(59, 130, 246, 0.12);
  border-radius: 10px;
  font-family: monospace;
}

.active-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #3b82f6;
  box-shadow: 0 0 6px rgba(59, 130, 246, 0.5);
}

.provider-actions {
  display: flex;
  gap: 0.25rem;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s;
}

.provider-header:hover .provider-actions {
  opacity: 1;
}

/* ── 模型列表 ── */
.model-list {
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding: 0.625rem 1rem 0.75rem 1rem;
}

.provider-detail {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.6875rem;
  color: #475569;
  padding: 0.5rem 0.625rem;
  margin-bottom: 0.5rem;
  background: rgba(255, 255, 255, 0.02);
  border-radius: 6px;
}

.detail-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}

.detail-label {
  flex-shrink: 0;
  font-size: 0.5625rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #334155;
  width: 2rem;
  text-align: right;
}

.detail-value {
  font-family: monospace;
  font-size: 0.6875rem;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.detail-url {
  color: #475569;
}

.model-item {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.5rem 0.625rem;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}

.model-item:hover {
  background: rgba(255, 255, 255, 0.04);
}

.model-item.active {
  background: rgba(59, 130, 246, 0.1);
}

.model-info {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0.625rem;
}

.model-name {
  font-size: 0.875rem;
  font-weight: 600;
  color: #e2e8f0;
  white-space: nowrap;
}

.model-item.active .model-name {
  color: #93c5fd;
  font-weight: 700;
}

.model-id {
  font-size: 0.75rem;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  flex: 1;
}

.model-active-badge {
  flex-shrink: 0;
  font-size: 0.5625rem;
  font-weight: 700;
  color: #60a5fa;
  padding: 0.125rem 0.4rem;
  background: rgba(59, 130, 246, 0.12);
  border-radius: 4px;
  letter-spacing: 0.06em;
}

.model-actions {
  display: flex;
  gap: 0.25rem;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s;
}

.model-item:hover .model-actions {
  opacity: 1;
}

.model-empty {
  text-align: center;
  padding: 1rem;
  font-size: 0.8125rem;
  color: #64748b;
}

.btn-add-model {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  width: 100%;
  padding: 0.5rem;
  margin-top: 0.375rem;
  background: transparent;
  border: 1px dashed rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: #64748b;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-add-model:hover { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.2); color: #94a3b8; }
.btn-add-model svg { width: 14px; height: 14px; }

.provider-empty {
  text-align: center;
  padding: 2rem;
  font-size: 0.8125rem;
  color: #64748b;
}

/* ── 按钮 ── */
.btn-icon {
  width: 28px;
  height: 28px;
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all 0.15s;
}
.btn-icon:hover { background: rgba(255,255,255,0.1); color: #e2e8f0; }
.btn-icon svg { width: 14px; height: 14px; }
.btn-icon-danger:hover { background: rgba(239,68,68,0.15); color: #fca5a5; }

.btn-add-provider {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  padding: 0.625rem;
  background: transparent;
  border: 1px dashed rgba(255, 255, 255, 0.15);
  border-radius: 10px;
  color: #94a3b8;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-add-provider:hover { background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.25); color: #e2e8f0; }
.btn-add-provider svg { width: 16px; height: 16px; }

/* ── 表单面板 ── */
.form-panel {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.form-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
  font-size: 0.9375rem;
  font-weight: 600;
  color: #e2e8f0;
}

.modal-form {
  display: flex;
  flex-direction: column;
  gap: 0.875rem;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.875rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.form-group label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.form-group input,
.form-select {
  padding: 0.5rem 0.75rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  color: #f1f5f9;
  font-size: 0.8125rem;
  outline: none;
  transition: border-color 0.15s;
}

.form-group input:focus,
.form-select:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}

.form-group input::placeholder { color: #475569; }

.form-select {
  cursor: pointer;
  appearance: none;
  -webkit-appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%2394A3B8' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.625rem center;
  padding-right: 1.75rem;
}
.form-select option { background: #1e293b; color: #f1f5f9; }

.form-error {
  font-size: 0.8125rem;
  color: #fca5a5;
  margin: 0;
  padding: 0.5rem 0.75rem;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 8px;
}

.form-success {
  font-size: 0.8125rem;
  color: #6ee7b7;
  margin: 0;
  padding: 0.5rem 0.75rem;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.2);
  border-radius: 8px;
}

.test-result {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  font-size: 0.8125rem;
  line-height: 1.5;
}
.test-result svg { width: 16px; height: 16px; flex-shrink: 0; margin-top: 1px; }

.test-success {
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.2);
  color: #6ee7b7;
}

.test-fail {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  color: #fca5a5;
}

.form-actions {
  display: flex;
  gap: 0.75rem;
}

.btn-test {
  flex: 1;
  padding: 0.5rem;
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 8px;
  color: #94a3b8;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-test:hover:not(:disabled) { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.25); color: #e2e8f0; }
.btn-test:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-save {
  flex: 1;
  padding: 0.5rem;
  background: linear-gradient(135deg, #3b82f6, #06b6d4);
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-save:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(59,130,246,0.3); }
.btn-save:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
