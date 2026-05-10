<script setup>
defineProps({
  info: { type: Object, default: null },
})

function formatSeconds(s) {
  if (!s) return ''
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
  return `${m}:${String(sec).padStart(2, '0')}`
}

function formatCount(n) {
  if (!n) return ''
  if (n >= 100000000) return (n / 100000000).toFixed(1) + '亿'
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return n.toLocaleString()
}
</script>

<template>
  <div v-if="info" class="w-full bg-white rounded-2xl shadow-sm border border-surface-200 overflow-hidden card-hover">
    <div class="flex flex-col md:flex-row gap-6 p-6">
      <!-- 封面 -->
      <div class="shrink-0 relative w-full md:w-72 aspect-video md:aspect-auto md:h-44 rounded-xl overflow-hidden bg-surface-100">
        <img
          v-if="info.thumbnail"
          :src="info.thumbnail"
          :alt="info.title"
          class="w-full h-full object-cover"
        />
        <div class="absolute bottom-2 right-2 px-2 py-0.5 bg-black/70 text-white text-xs rounded">
          {{ info.duration_string || formatSeconds(info.duration) }}
        </div>
      </div>

      <!-- 信息 -->
      <div class="flex flex-col gap-3 min-w-0 flex-1">
        <h3 class="text-lg font-semibold text-surface-800 leading-snug line-clamp-2">
          {{ info.title }}
        </h3>

        <div class="flex flex-wrap items-center gap-3 text-sm text-surface-800/50">
          <span v-if="info.uploader" class="flex items-center gap-1">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
            {{ info.uploader }}
          </span>
          <span v-if="info.view_count" class="flex items-center gap-1">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
            {{ formatCount(info.view_count) }} 次观看
          </span>
          <span v-if="info.extractor" class="px-2 py-0.5 bg-primary-50 text-primary-600 rounded text-xs font-medium">
            {{ info.extractor }}
          </span>
        </div>

        <p v-if="info.description" class="text-sm text-surface-800/40 line-clamp-2 leading-relaxed">
          {{ info.description }}
        </p>
      </div>
    </div>
  </div>
</template>