<script setup>
import ConnectionItem from './ConnectionItem.vue'

defineProps({
  connections: { type: Array, required: true },
  active: { type: Object, required: true },
  pending: { type: Object, required: true },
  loadError: { type: String, default: '' },
  connectionFeedback: { type: Object, required: true },
  modelFeedback: { type: Object, required: true },
})

defineEmits(['edit', 'delete', 'refresh', 'test', 'switch', 'retry', 'clear-model-feedback'])
</script>

<template>
  <div class="connections" aria-live="polite" :aria-busy="pending.load">
    <div v-if="pending.load" class="skeleton-list" aria-label="正在加载 AI 连接">
      <div v-for="index in 3" :key="index" class="skeleton-row">
        <span class="skeleton-block skeleton-block--title"></span>
        <span class="skeleton-block skeleton-block--model"></span>
        <span class="skeleton-block skeleton-block--actions"></span>
      </div>
    </div>

    <div v-else-if="loadError" class="load-error" role="alert">
      <div>
        <strong>无法加载 AI 连接</strong>
        <span>{{ loadError }}</span>
      </div>
      <button type="button" @click="$emit('retry')">重试</button>
    </div>

    <template v-else>
      <ConnectionItem
        v-for="connection in connections"
        :key="connection.id"
        :connection="connection"
        :active="active"
        :pending="pending"
        :connection-feedback="connectionFeedback[connection.id]"
        :model-feedback="modelFeedback"
        @edit="$emit('edit', $event)"
        @delete="$emit('delete', $event)"
        @refresh="$emit('refresh', $event)"
        @test="(connectionId, modelId) => $emit('test', connectionId, modelId)"
        @switch="(connectionId, modelId) => $emit('switch', connectionId, modelId)"
        @clear-model-feedback="$emit('clear-model-feedback', $event)"
      />
      <div v-if="connections.length === 0" class="empty">
        <strong>还没有 AI 连接</strong>
        <span>添加中转站后即可选择和测试模型</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.connections{display:grid;gap:8px}.skeleton-list{display:grid;gap:8px}.skeleton-row{min-height:58px;display:grid;grid-template-columns:minmax(100px,.7fr) minmax(120px,1fr) 120px;align-items:center;gap:16px;padding:0 16px;border:1px solid var(--border);border-radius:8px;background:rgba(15,23,42,.28)}.skeleton-block{display:block;height:11px;border-radius:4px;background:rgba(148,163,184,.13);animation:pulse 1.4s ease-in-out infinite}.skeleton-block--title{width:65%}.skeleton-block--model{width:82%}.skeleton-block--actions{height:28px}.load-error{min-height:150px;display:flex;align-items:center;justify-content:center;gap:20px;padding:24px;border:1px solid rgba(239,68,68,.26);border-radius:8px;background:rgba(239,68,68,.07)}.load-error div{display:grid;gap:5px}.load-error strong{font-size:14px;color:#fecaca}.load-error span{font-size:12px;color:#fca5a5}.load-error button{min-width:76px;min-height:40px;border:1px solid rgba(239,68,68,.42);border-radius:6px;background:transparent;color:#fecaca;font-weight:600;cursor:pointer}.load-error button:hover{background:rgba(239,68,68,.1)}.load-error button:focus-visible{outline:2px solid var(--accent-blue);outline-offset:2px}.empty{display:grid;place-items:center;gap:5px;min-height:150px;border:1px dashed var(--border-hover);border-radius:8px;color:var(--text-secondary)}.empty strong{font-size:14px}.empty span{font-size:12px;color:var(--text-muted)}@keyframes pulse{50%{opacity:.42}}@media(max-width:560px){.skeleton-row{grid-template-columns:minmax(0,1fr) 84px}.skeleton-block--model{grid-row:2}.skeleton-block--actions{grid-column:2;grid-row:1/3}.load-error{align-items:stretch;flex-direction:column}.load-error button{width:100%}}@media(prefers-reduced-motion:reduce){.skeleton-block{animation:none}}
</style>
