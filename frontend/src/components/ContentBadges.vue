<script setup>
import { computed, ref, useId } from 'vue'
const props = defineProps({ content: Object, totalParts: { type: Number, default: 1 }, subtitleParts: Array, organizedParts: Array })
const id = useId()
const dismissed = ref(false)
const names = { summary: '摘要', mindmap: '思维导图', notes: '笔记', qa: '问答' }
const badges = computed(() => {
  if (props.totalParts > 1) {
    const sub = props.subtitleParts?.length || 0
    const organized = props.organizedParts?.length || 0
    return [
      ...(sub ? [{ text: `有字幕 ${sub}/${props.totalParts}P`, detail: `${sub} 个分 P 已保存字幕，可直接阅读。`, tone: 'subtitle' }] : []),
      ...(organized ? [{ text: `已整理 ${organized}/${props.totalParts}P`, detail: `${organized} 个分 P 已保存至少一种 AI 学习资料，展开可查看每个分 P 的详情。`, tone: 'organized' }] : []),
    ]
  }
  const state = props.content || {}
  const result = []
  if (state.module_count) {
    const modules = (state.modules || []).map(m => names[m]).filter(Boolean).join('、')
    const update = state.stale_modules?.length ? '部分资料生成后字幕或提示词已更新，可在工作台重新生成。' : ''
    result.push({ text: `已整理 · ${state.module_count}/4`, detail: `已保存${modules || `${state.module_count} 种学习资料`}。${state.has_subtitle ? '字幕已缓存。' : ''}${update}`, tone: 'organized' })
  } else if (state.has_subtitle) result.push({ text: '有字幕', detail: '字幕已缓存，可以直接阅读；尚未生成 AI 学习资料。', tone: 'subtitle' })
  if (state.has_description_summary && !state.module_count) result.push({ text: '简介摘要', detail: '仅根据视频简介生成，不代表已整理视频全文。', tone: 'description' })
  return result
})
</script>

<template>
  <span v-if="badges.length" class="content-badges" @click.stop>
    <span v-for="(badge, index) in badges" :key="badge.tone" class="content-badge" :class="`content-badge--${badge.tone}`" tabindex="0"
      :aria-describedby="`${id}-${index}`" @mouseenter="dismissed = false" @focus="dismissed = false" @keydown.esc="dismissed = true">
      {{ badge.text }}
      <span :id="`${id}-${index}`" role="tooltip" class="badge-explanation" :class="{ dismissed }">{{ badge.detail }}</span>
    </span>
  </span>
</template>

<style scoped>
.content-badges { display: inline-flex; flex-wrap: wrap; gap: 6px; align-items: center; max-width: 100%; }
.content-badge { position: relative; display: inline-block; border-radius: 6px; padding: 3px 7px; font-size: 12px; font-weight: 500; white-space: nowrap; line-height: 1.5; cursor: help; }
.content-badge--subtitle { color: var(--accent-cyan); background: color-mix(in srgb, var(--accent-cyan) 12%, transparent); }
.content-badge--organized { color: #34d399; background: rgba(52,211,153,.12); }
.content-badge--description { color: var(--text-secondary); background: var(--bg-secondary); }
.content-badge:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 3px; }
.badge-explanation { display: none; position: absolute; left: 0; bottom: calc(100% + 6px); width: max-content; max-width: min(240px, 60vw); white-space: normal; padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-primary); color: var(--text-primary); box-shadow: 0 4px 16px #0003; z-index: 20; }
.content-badge:hover .badge-explanation:not(.dismissed), .content-badge:focus .badge-explanation:not(.dismissed) { display: block; }
</style>
