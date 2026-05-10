<script setup>
import { computed } from 'vue'

const props = defineProps({
  formats: { type: Array, default: () => [] },
  modelValue: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

// 分类格式
const qualityGroups = computed(() => {
  const combined = props.formats
    .filter((f) => f.is_combined && f.height)
    .sort((a, b) => (b.height || 0) - (a.height || 0))

  // 去重（同分辨率取第一项）
  const seen = new Set()
  const unique = combined.filter((f) => {
    const key = `${f.height}_${f.ext}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })

  return unique.slice(0, 8)
})

const videoOnlyFormats = computed(() =>
  props.formats
    .filter((f) => f.is_video_only && f.height)
    .sort((a, b) => (b.height || 0) - (a.height || 0))
    .slice(0, 8)
)

const audioFormats = computed(() =>
  props.formats.filter((f) => f.is_audio_only).slice(0, 5)
)

const bestFormat = computed(() => {
  const combined = qualityGroups.value
  if (combined.length) return combined[0].format_id
  return 'best'
})

function selectFormat(formatId) {
  emit('update:modelValue', formatId)
}

function formatLabel(f) {
  const parts = []
  if (f.height) parts.push(f.height + 'p')
  if (f.format_note) parts.push(f.format_note)
  return parts.join(' ') || f.ext.toUpperCase()
}
</script>

<template>
  <div v-if="formats.length" class="w-full space-y-5">
    <!-- 推荐格式：合并流 -->
    <div v-if="qualityGroups.length">
      <p class="text-sm font-medium text-surface-800/60 mb-3">推荐清晰度（视频+音频）</p>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="f in qualityGroups"
          :key="f.format_id"
          @click="selectFormat(f.format_id)"
          class="px-4 py-2.5 rounded-xl text-sm font-medium transition-all border-2"
          :class="modelValue === f.format_id
            ? 'border-primary-500 bg-primary-50 text-primary-600 shadow-sm'
            : 'border-surface-200 bg-white text-surface-800 hover:border-surface-300'"
        >
          <div class="flex items-center gap-2">
            <span>{{ formatLabel(f) }}</span>
            <span class="text-xs text-surface-800/40">{{ f.ext.toUpperCase() }}</span>
            <span v-if="f.filesize_str" class="text-xs text-surface-800/30">{{ f.filesize_str }}</span>
          </div>
        </button>
      </div>
    </div>

    <!-- 纯视频流 -->
    <div v-if="videoOnlyFormats.length">
      <p class="text-sm font-medium text-surface-800/60 mb-3">仅视频（需配合音频一起下载）</p>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="f in videoOnlyFormats"
          :key="f.format_id"
          @click="selectFormat(f.format_id)"
          class="px-3 py-2 rounded-xl text-xs font-medium transition-all border-2"
          :class="modelValue === f.format_id
            ? 'border-primary-500 bg-primary-50 text-primary-600'
            : 'border-surface-200 bg-white text-surface-800 hover:border-surface-300'"
        >
          {{ formatLabel(f) }}
          <span class="ml-1 text-surface-800/30">{{ f.ext }}</span>
        </button>
      </div>
    </div>

    <!-- 纯音频 -->
    <div v-if="audioFormats.length">
      <p class="text-sm font-medium text-surface-800/60 mb-3">仅音频</p>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="f in audioFormats"
          :key="f.format_id"
          @click="selectFormat(f.format_id)"
          class="px-3 py-2 rounded-xl text-xs font-medium transition-all border-2"
          :class="modelValue === f.format_id
            ? 'border-primary-500 bg-primary-50 text-primary-600'
            : 'border-surface-200 bg-white text-surface-800 hover:border-surface-300'"
        >
          {{ f.ext.toUpperCase() }}
          <span v-if="f.filesize_str" class="ml-1 text-surface-800/30">{{ f.filesize_str }}</span>
        </button>
      </div>
    </div>
  </div>
</template>