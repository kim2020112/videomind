<script setup>
import { computed } from 'vue'

const props = defineProps({
  tasks: { type: Array, default: () => [] },
})

const emit = defineEmits(['open-history'])

const primaryTask = computed(() => props.tasks[0] || null)
const progress = computed(() => Math.max(0, Math.min(100, Math.round(primaryTask.value?.progress || 0))))
const stageLabel = computed(() => {
  const task = primaryTask.value
  if (!task) return ''
  return task.message || {
    queued: '等待后台处理',
    downloading: '正在下载音频',
    transcribing: '正在转录字幕',
    generating: '正在生成学习内容',
  }[task.status] || '后台处理中'
})
</script>

<template>
  <button
    v-if="tasks.length"
    type="button"
    class="task-progress-dock"
    aria-label="查看后台任务进度"
    @click="emit('open-history')"
  >
    <span class="task-progress-dock__icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6l4 2m5-2a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>
    </span>
    <span class="task-progress-dock__content">
      <span class="task-progress-dock__title">{{ tasks.length }} 个后台任务</span>
      <span class="task-progress-dock__stage">{{ stageLabel }}</span>
      <span class="task-progress-dock__track" aria-hidden="true">
        <span class="task-progress-dock__fill" :style="{ width: `${progress}%` }"></span>
      </span>
    </span>
    <span class="task-progress-dock__percent">{{ progress }}%</span>
  </button>
</template>

<style scoped>
.task-progress-dock {
  position: fixed;
  right: 1.25rem;
  bottom: 1.25rem;
  z-index: 90;
  width: min(360px, calc(100vw - 2rem));
  min-height: 64px;
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border: 1px solid rgba(59, 130, 246, 0.35);
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.94);
  box-shadow: 0 16px 45px rgba(0, 0, 0, 0.35);
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  backdrop-filter: blur(16px);
}

.task-progress-dock:hover {
  border-color: rgba(59, 130, 246, 0.6);
  transform: translateY(-1px);
}

.task-progress-dock__icon {
  width: 40px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: rgba(59, 130, 246, 0.14);
  color: #93c5fd;
}

.task-progress-dock__icon svg {
  width: 22px;
  height: 22px;
}

.task-progress-dock__content {
  min-width: 0;
  display: grid;
  gap: 0.2rem;
}

.task-progress-dock__title {
  font-size: 0.8125rem;
  font-weight: 700;
}

.task-progress-dock__stage {
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 0.75rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-progress-dock__track {
  height: 4px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
}

.task-progress-dock__fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--accent-blue), var(--accent-cyan));
  transition: width 0.25s ease;
}

.task-progress-dock__percent {
  color: #93c5fd;
  font-size: 0.75rem;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
}

@media (max-width: 768px) {
  .task-progress-dock {
    right: 0.75rem;
    bottom: calc(0.75rem + env(safe-area-inset-bottom));
    width: calc(100vw - 1.5rem);
  }
}
</style>
