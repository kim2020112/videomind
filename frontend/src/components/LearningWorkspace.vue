<script setup>
import { computed } from 'vue'
import AiSummary from './AiSummary.vue'
import SubtitlePanel from './SubtitlePanel.vue'
defineOptions({ inheritAttrs: false })
const props = defineProps({
  result: Object, loading: Boolean, error: String, subtitleText: String, subtitleInfo: Object,
  subtitleError: String, visitError: String, subtitleCleared: Boolean, onClearSubtitle: Function, videoTitle: String, backgroundTask: Object, currentVideoTime: Number,
  moduleStates: { type: Object, default: () => ({}) },
  selectedTargets: { type: Array, default: () => ['summary', 'mindmap', 'notes', 'qa'] },
  submitting: Boolean, descriptionSummary: Object, descriptionAvailable: Boolean,
  onGenerateTargets: Function, onResumeTask: Function, onCancelTask: Function,
  onFetchSubtitle: Function, onSeekVideo: Function,
})
const emit = defineEmits(['update:selectedTargets'])
const modules = [['summary', '摘要'], ['mindmap', '导图'], ['notes', '笔记'], ['qa', '精选问答']]
const busy = computed(() => props.submitting || ['queued', 'downloading', 'transcribing', 'generating', 'awaiting_confirmation'].includes(props.backgroundTask?.status))
const waiting = computed(() => props.backgroundTask?.status === 'awaiting_confirmation')
const taskVisible = computed(() => busy.value && props.backgroundTask)
const fallback = computed(() => !props.subtitleText && props.descriptionAvailable && props.backgroundTask?.status === 'failed' && props.backgroundTask?.result?.subtitle_unavailable)
function toggle(target) {
  emit('update:selectedTargets', props.selectedTargets.includes(target) ? props.selectedTargets.filter(t => t !== target) : [...props.selectedTargets, target])
}
function status(target) {
  const state = props.moduleStates[target]
  if (state?.status === 'generating') return '生成中'
  if (state?.status === 'queued') return '等待中'
  if (state?.stale) return '基于旧版字幕或提示词'
  if (state?.version_unknown) return '已完成 · 版本未知'
  return { queued: '等待中', generating: '生成中', done: '已完成', failed: '失败，可重试' }[state?.status] || '未生成'
}
</script>

<template>
  <div class="learning-workspace">
    <p v-if="visitError" role="status">{{ visitError }}</p>
    <SubtitlePanel :text="subtitleText" :info="subtitleInfo" :title="videoTitle" :busy="busy" :error="subtitleError"
      :cleared="subtitleCleared" :onClear="onClearSubtitle" :currentTime="currentVideoTime" :onFetch="refresh => onFetchSubtitle?.(Boolean(refresh))" :onSeek="onSeekVideo" />
    <section v-if="taskVisible" class="learning-task" aria-label="后台任务" aria-live="polite">
      <strong>{{ backgroundTask.message || '等待后台处理' }}</strong>
      <template v-if="waiting">
        <p>语音转录预计需要 {{ Math.max(1, Math.ceil((backgroundTask.estimated_seconds || 0) / 60)) }} 分钟。{{ backgroundTask.payload?.targets?.length ? '完成后将继续生成所选资料。' : '完成后可查看字幕。' }}</p>
        <button type="button" :disabled="submitting" @click="onResumeTask?.()">开始语音转录</button>
      </template>
      <template v-else>
        <progress :value="backgroundTask.progress || 0" max="100" aria-label="后台处理进度"></progress>
        <p>可离开页面继续浏览，返回后自动恢复进度。{{ backgroundTask.queue_position ? `队列第 ${backgroundTask.queue_position} 位` : '' }}</p>
      </template>
      <button type="button" class="quiet" :disabled="submitting" @click="onCancelTask?.()">取消任务</button>
    </section>
    <section class="learning-materials" aria-label="AI 学习资料">
      <div class="learning-heading"><div><h2>AI 学习资料</h2><p>基于当前视频字幕生成；已有资料自动复用，也可以按需补充。</p></div></div>
      <fieldset :disabled="busy" class="module-choices">
        <legend class="sr-only">选择需要生成的学习资料</legend>
        <label v-for="[target, label] in modules" :key="target" :class="{ selected: selectedTargets.includes(target) }">
          <input type="checkbox" :checked="selectedTargets.includes(target)" @change="toggle(target)" />
          <span>{{ label }}<small>{{ status(target) }}</small></span>
        </label>
      </fieldset>
      <div class="generate-actions">
        <button type="button" class="generate-button" :disabled="busy || !selectedTargets.length" @click="onGenerateTargets?.(selectedTargets)">
          {{ busy ? '任务处理中' : selectedTargets.length === 4 ? '全部生成' : `生成所选内容（${selectedTargets.length}）` }}
        </button>
        <span>每次生成操作最多计 1 次，读取缓存和获取字幕不计次</span>
      </div>
      <p v-if="error" role="alert" class="learning-error">{{ error }}</p>
      <div v-for="[target, label] in modules.filter(([key]) => moduleStates[key]?.status === 'failed')" :key="target" class="module-error">
        <span>{{ label }}：{{ moduleStates[target].error }}</span>
        <button type="button" :disabled="busy" @click="onGenerateTargets?.([target], true)">重试{{ label }}</button>
      </div>
      <div v-if="fallback" class="description-fallback">
        <p>无法取得视频全文，可仅根据视频简介生成摘要。该结果不会代表完整视频内容。</p>
        <button type="button" :disabled="busy" @click="onGenerateTargets?.(['summary'], false, 'description')">仅根据简介生成摘要</button>
      </div>
      <div v-if="descriptionSummary" class="description-result"><strong>基于视频简介 · 未分析视频全文</strong><p>{{ descriptionSummary.summary }}</p></div>
      <AiSummary v-bind="$attrs" :workspaceMode="true" :moduleStates="moduleStates" :result="result" :loading="busy" :error="''"
        :subtitleText="subtitleText" :subtitleInfo="subtitleInfo" :subtitleError="subtitleError" :videoTitle="videoTitle"
        :backgroundTask="null" :currentVideoTime="currentVideoTime" :onFetchSubtitle="onFetchSubtitle" :onSeekVideo="onSeekVideo" />
    </section>
  </div>
</template>

<style scoped>
.learning-workspace { display: grid; grid-template-columns: minmax(0, 1fr); gap: 1.5rem; min-width: 0; }
.learning-materials { min-width: 0; }
h2 { margin: 0; font-size: 1.125rem; color: var(--text-primary); font-weight: 650; }
p { margin: .5rem 0; color: var(--text-secondary); font-size: .8125rem; line-height: 1.7; }
.module-choices { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .65rem; padding: 0; border: 0; margin: 1.2rem 0; }
.module-choices label { display: flex; align-items: center; gap: .6rem; min-height: 70px; padding: .8rem; border: 1px solid var(--border); border-radius: 10px; cursor: pointer; font-size: .875rem; }
.module-choices label.selected { border-color: var(--accent-blue); background: color-mix(in srgb, var(--accent-blue) 8%, transparent); }
.module-choices input { width: 17px; height: 17px; accent-color: var(--accent-blue); flex-shrink: 0; }
.module-choices small { display: block; font-size: .6875rem; color: var(--text-secondary); margin-top: .25rem; }
.module-choices:disabled { opacity: .7; }
button { min-height: 44px; border: 1px solid var(--border); border-radius: 8px; padding: .6rem 1rem; cursor: pointer; background: var(--bg-secondary); color: var(--text-primary); }
button:disabled { opacity: .5; cursor: not-allowed; }
button:focus-visible, input:focus-visible { outline: 2px solid var(--accent-blue); outline-offset: 3px; }
.generate-actions { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; margin-bottom: 1.5rem; }
.generate-button { background: var(--accent-blue); color: white; border-color: var(--accent-blue); font-weight: 600; }
.generate-actions span { color: var(--text-secondary); font-size: .75rem; }
.learning-task { padding: 1rem 1.2rem; border: 1px solid var(--accent-blue); border-radius: 12px; background: color-mix(in srgb, var(--accent-blue) 7%, transparent); font-size: .875rem; }
.learning-task button { margin: .5rem .5rem 0 0; }
.learning-task progress { display: block; width: 100%; height: 6px; margin-top: .8rem; accent-color: var(--accent-blue); }
.learning-error, .module-error { color: #fca5a5; font-size: .8125rem; overflow-wrap: anywhere; }
.module-error { display: flex; justify-content: space-between; gap: 1rem; align-items: center; margin-bottom: .6rem; }
.module-error button { flex-shrink: 0; }
.description-result, .description-fallback { margin-bottom: 1rem; padding: 1rem; border: 1px solid var(--border); border-radius: 10px; }
.description-result strong { font-size: .8125rem; color: #fcd34d; }
.description-result p { white-space: pre-wrap; }
@media (max-width: 640px) { .module-choices { grid-template-columns: repeat(2, minmax(0, 1fr)); } .module-choices label { min-height: 64px; } .module-error { align-items: flex-start; flex-wrap: wrap; } .generate-button { width: 100%; } }
</style>
