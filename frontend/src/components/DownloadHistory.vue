<script setup>
defineProps({
  history: { type: Array, default: () => [] },
})

defineEmits(['download-file'])
</script>

<template>
  <div v-if="history.length" class="w-full bg-white rounded-2xl shadow-sm border border-surface-200 overflow-hidden">
    <div class="px-6 py-4 border-b border-surface-100">
      <h3 class="text-base font-semibold text-surface-800">下载记录</h3>
    </div>
    <div class="divide-y divide-surface-100">
      <div
        v-for="item in history"
        :key="item.task_id"
        class="px-6 py-3.5 flex items-center justify-between gap-4"
      >
        <div class="min-w-0 flex-1">
          <p class="text-sm font-medium text-surface-800 truncate">{{ item.title }}</p>
          <p class="text-xs text-surface-800/40 mt-0.5">
            {{ item.status === 'completed' ? '已完成' : '失败' }}
          </p>
        </div>
        <button
          v-if="item.status === 'completed'"
          @click="$emit('download-file', item.task_id)"
          class="shrink-0 px-4 py-2 text-sm font-medium text-white bg-primary-500 hover:bg-primary-600 rounded-lg transition-colors"
        >
          保存文件
        </button>
      </div>
    </div>
  </div>
</template>