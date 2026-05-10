<script setup>
import { ref } from 'vue'

const emit = defineEmits(['parse'])

const url = ref('')
const loading = ref(false)

async function handlePaste() {
  try {
    const text = await navigator.clipboard.readText()
    if (text) {
      url.value = text.trim()
    }
  } catch {
    // 剪贴板读取失败，静默处理
  }
}

async function handleParse() {
  if (!url.value.trim()) return
  loading.value = true
  emit('parse', url.value.trim())
}

function clear() {
  url.value = ''
  emit('parse', '')
}

defineExpose({ setLoading: (v) => (loading.value = v) })
</script>

<template>
  <div class="w-full">
    <div class="relative flex items-stretch shadow-2xl rounded-3xl overflow-hidden border-2 border-surface-200 bg-white input-focus">
      <div class="flex-1 flex items-center px-4">
        <svg class="w-5 h-5 text-surface-800/30 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
        </svg>
        <input
          v-model="url"
          type="text"
          placeholder="粘贴视频链接，例如 https://www.youtube.com/watch?v=..."
          class="flex-1 py-4 px-3 text-surface-800 placeholder-surface-800/30 outline-none bg-transparent text-base"
          @keyup.enter="handleParse"
        />
        <button
          v-if="url"
          @click="clear"
          class="p-1.5 rounded-full hover:bg-surface-100 transition-colors shrink-0"
          title="清除"
        >
          <svg class="w-4 h-4 text-surface-800/40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
      <button
        @click="handlePaste"
        class="px-4 text-sm text-surface-800/50 hover:text-primary-500 hover:bg-surface-50 transition-colors border-l border-surface-200 shrink-0"
        title="从剪贴板粘贴"
      >
        粘贴
      </button>
      <button
        @click="handleParse"
        :disabled="!url.trim() || loading"
        class="px-8 font-medium text-white btn-gradient disabled:opacity-50 disabled:cursor-not-allowed shrink-0 flex items-center gap-2"
      >
        <svg v-if="loading" class="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        {{ loading ? '解析中...' : '解析视频' }}
      </button>
    </div>
  </div>
</template>