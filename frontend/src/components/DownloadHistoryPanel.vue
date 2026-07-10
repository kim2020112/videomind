<script setup>
import { formatTime } from '../utils/resultFormatters.js'

defineProps({
  history: { type: Array, default: () => [] },
  desktop: { type: Boolean, default: false },
})

defineEmits(['download-file'])
</script>

<template>
  <div v-if="history.length" class="history-card" :class="{ 'history-card--desktop': desktop }">
    <p class="history-label">下载记录</p>
    <div class="history-list">
      <div v-for="item in history" :key="item.task_id" class="history-item">
        <svg v-if="item.status === 'completed'" class="history-status-icon history-status-success" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>
        <svg v-else class="history-status-icon history-status-error" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/></svg>
        <div class="history-item-content">
          <span class="history-title">{{ item.title }}</span>
          <span v-if="item.time" class="history-time">{{ formatTime(item.time) }}</span>
        </div>
        <button
          v-if="item.status === 'completed'"
          type="button"
          @click="$emit('download-file', item.task_id)"
          class="save-button"
        >
          <svg viewBox="0 0 20 20" fill="currentColor" class="save-icon"><path d="M10.75 2.75a.75.75 0 00-1.5 0v8.614L6.295 8.235a.75.75 0 10-1.09 1.03l4.25 4.5a.75.75 0 001.09 0l4.25-4.5a.75.75 0 00-1.09-1.03l-2.955 3.129V2.75z"/><path d="M3.5 12.75a.75.75 0 00-1.5 0v2.5A2.75 2.75 0 004.75 18h10.5A2.75 2.75 0 0018 15.25v-2.5a.75.75 0 00-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5z"/></svg>
          保存
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.history-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 1.5rem;
  backdrop-filter: blur(12px);
}

.history-card--desktop {
  margin-top: 1rem;
}

.history-label {
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 1rem;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border);
  border-radius: 10px;
}

.history-status-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.history-status-success {
  color: var(--success);
}

.history-status-error {
  color: var(--error);
}

.history-item-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.history-title {
  font-size: 0.8125rem;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-time {
  font-size: 0.6875rem;
  color: var(--text-muted);
}

.save-button {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.4375rem 1rem;
  background: transparent;
  border: 1px solid var(--accent-blue);
  border-radius: 8px;
  color: var(--accent-blue);
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
  flex-shrink: 0;
}

.save-button:hover {
  background: rgba(59, 130, 246, 0.15);
}

.save-icon {
  width: 16px;
  height: 16px;
}

@media (max-width: 768px) {
  .history-item {
    flex-wrap: wrap;
  }

  .history-item-content {
    width: calc(100% - 42px);
  }

  .save-button {
    width: 100%;
    margin-top: 0.25rem;
    justify-content: center;
  }
}
</style>
