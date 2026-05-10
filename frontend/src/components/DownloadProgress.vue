<script setup>
defineProps({
  progress: { type: Object, default: null },
})

const statusLabels = {
  pending: '等待中',
  downloading: '下载中',
  processing: '处理中',
  completed: '下载完成',
  failed: '下载失败',
}
</script>

<template>
  <div v-if="progress" class="w-full bg-white rounded-2xl shadow-sm border border-surface-200 p-6">
    <!-- 状态头部 -->
    <div class="flex items-center justify-between mb-4">
      <div class="flex items-center gap-2">
        <div
          class="w-2.5 h-2.5 rounded-full"
          :class="{
            'bg-yellow-400': progress.status === 'pending',
            'bg-blue-500 progress-active': progress.status === 'downloading',
            'bg-yellow-500': progress.status === 'processing',
            'bg-green-500': progress.status === 'completed',
            'bg-red-500': progress.status === 'failed',
          }"
        />
        <span class="text-sm font-medium text-surface-800">
          {{ statusLabels[progress.status] || progress.status }}
        </span>
      </div>
      <span class="text-sm font-bold text-primary-600">{{ progress.percent }}%</span>
    </div>

    <!-- 进度条 -->
    <div class="w-full h-2 bg-surface-100 rounded-full overflow-hidden mb-3">
      <div
        class="h-full rounded-full transition-all duration-300 ease-out"
        :class="progress.status === 'failed' ? 'bg-red-500' : 'bg-gradient-to-r from-primary-500 to-accent-500'"
        :style="{ width: progress.percent + '%' }"
      />
    </div>

    <!-- 详情 -->
    <div class="flex items-center gap-4 text-xs text-surface-800/50">
      <span v-if="progress.speed">{{ progress.speed }}</span>
      <span v-if="progress.eta && progress.eta > 0">
        剩余约 {{ Math.ceil(progress.eta) }} 秒
      </span>
      <span v-if="progress.downloaded && progress.total">
        {{ (progress.downloaded / 1024 / 1024).toFixed(1) }} / {{ (progress.total / 1024 / 1024).toFixed(1) }} MB
      </span>
    </div>

    <!-- 错误信息 -->
    <div v-if="progress.status === 'failed' && progress.error" class="mt-3 p-3 bg-red-50 rounded-lg text-sm text-red-600">
      {{ progress.error }}
    </div>
  </div>
</template>