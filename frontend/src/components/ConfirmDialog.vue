<script setup>
import BaseDialog from './BaseDialog.vue'

defineProps({
  visible: Boolean,
  title: { type: String, default: '确认操作' },
  message: { type: String, required: true },
  confirmLabel: { type: String, default: '确认' },
  cancelLabel: { type: String, default: '取消' },
  danger: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['confirm', 'close'])
</script>

<template>
  <BaseDialog
    :visible="visible"
    title-id="confirm-dialog-title"
    close-label="关闭确认弹窗"
    initial-focus="[data-confirm-cancel]"
    layer="confirmation"
    @close="emit('close')"
  >
    <h2 id="confirm-dialog-title" class="confirm-title">{{ title }}</h2>
    <p class="confirm-message">{{ message }}</p>
    <div class="confirm-actions">
      <button type="button" class="confirm-button confirm-button--secondary" data-confirm-cancel @click="emit('close')">
        {{ cancelLabel }}
      </button>
      <button
        type="button"
        class="confirm-button"
        :class="danger ? 'confirm-button--danger' : 'confirm-button--primary'"
        :disabled="busy"
        @click="emit('confirm')"
      >
        {{ busy ? '处理中…' : confirmLabel }}
      </button>
    </div>
  </BaseDialog>
</template>

<style scoped>
.confirm-title {
  margin: 0 3rem 0.75rem 0;
  font-size: 1.125rem;
  color: var(--text-primary);
}

.confirm-message {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.7;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 1.5rem;
}

.confirm-button {
  min-width: 96px;
  min-height: 44px;
  padding: 0.625rem 1rem;
  border-radius: 9px;
  font-weight: 600;
  cursor: pointer;
}

.confirm-button--secondary {
  border: 1px solid var(--border-hover);
  background: transparent;
  color: var(--text-secondary);
}

.confirm-button--primary {
  border: 1px solid var(--accent-blue);
  background: var(--accent-blue);
  color: #fff;
}

.confirm-button--danger {
  border: 1px solid rgba(239, 68, 68, 0.5);
  background: #b91c1c;
  color: #fff;
}

.confirm-button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
</style>
