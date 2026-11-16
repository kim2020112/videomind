<script setup>
import { computed, reactive, watch } from 'vue'
import { usePlatformConfig } from '../composables/usePlatformConfig.js'

const emit = defineEmits(['dirty-change', 'busy-change'])
const api = usePlatformConfig()
const cookies = reactive({ bilibili: '', douyin: '' })
const show = reactive({ bilibili: false, douyin: false })
const labels = { bilibili: 'B站', douyin: '抖音' }
const statusLabels = { valid: '登录有效', invalid: '登录失效', unknown: '暂无法确认', untested: '待验证' }
const hints = {
  bilibili: '使用已登录 B站网页的完整 Cookie，需包含 SESSDATA。',
  douyin: '使用已登录抖音网页的完整 Cookie。风控或签名限制时会提示暂无法确认。',
}
const status = platform => api.platforms.value[platform] || {}
const dirty = computed(() => Object.values(cookies).some(value => value.trim()))
watch(dirty, value => emit('dirty-change', value), { immediate: true })
watch(() => Boolean(api.pending.bilibili || api.pending.douyin), value => emit('busy-change', value))
async function save(platform) {
  if (await api.save(platform, cookies[platform])) cookies[platform] = ''
}
api.load()
</script>

<template>
  <section class="platform-config" aria-labelledby="platform-config-title">
    <header class="platform-heading">
      <h3 id="platform-config-title">平台 Cookie</h3>
      <p>管理平台登录态，可手动验证；实际使用方式见各平台状态。</p>
    </header>
    <div v-if="api.pending.load" class="platform-loading" role="status">正在加载平台配置…</div>
    <div v-else-if="api.loadError.value" class="platform-feedback platform-feedback--error" role="alert">
      {{ api.loadError.value }} <button type="button" @click="api.load">重试</button>
    </div>
    <div v-else class="platform-grid">
      <article v-for="platform in ['bilibili', 'douyin']" :key="platform" class="platform-card">
        <div class="platform-card__top">
          <div><h4>{{ labels[platform] }}</h4><p>{{ status(platform).configured ? (status(platform).source === 'environment' ? '已配置 · 环境变量' : '已配置 · 手动保存') : '尚未配置' }}</p></div>
          <span class="platform-status" :class="`platform-status--${status(platform).status || 'untested'}`">{{ statusLabels[status(platform).status] || '待验证' }}</span>
        </div>
        <div class="platform-field">
          <label :for="`${platform}-cookie`">Cookie</label>
          <div class="cookie-input">
            <input :id="`${platform}-cookie`" v-model="cookies[platform]" :type="show[platform] ? 'text' : 'password'" :placeholder="status(platform).configured ? '粘贴新 Cookie，留空保留现有配置' : '粘贴完整 Cookie 字符串'" :disabled="Boolean(api.pending[platform])" :aria-describedby="`${platform}-hint`" autocomplete="off" spellcheck="false">
            <button type="button" :aria-label="`${show[platform] ? '隐藏' : '显示'}${labels[platform]} Cookie`" :aria-pressed="show[platform]" @click="show[platform] = !show[platform]">{{ show[platform] ? '隐藏' : '显示' }}</button>
          </div>
          <small :id="`${platform}-hint`">{{ hints[platform] }}</small>
        </div>
        <div class="platform-actions">
          <button type="button" class="secondary-button" :disabled="Boolean(api.pending[platform])" @click="save(platform)">{{ api.pending[platform] === 'save' ? '保存中…' : '保存 Cookie' }}</button>
          <button type="button" class="ghost-button" :disabled="Boolean(api.pending[platform]) || (!cookies[platform].trim() && !status(platform).configured)" @click="api.validate(platform, cookies[platform])">{{ api.pending[platform] === 'validate' ? '验证中…' : cookies[platform].trim() ? '验证新 Cookie' : '验证有效性' }}</button>
        </div>
        <p v-if="status(platform).used_for_requests === false" class="platform-note">自动任务当前使用匿名访问；保存 Cookie 不会解除平台访问保护。</p>
        <p v-if="cookies[platform].trim()" class="platform-note">验证仅检查当前输入，点击保存后才会替换已有配置。</p>
        <p v-if="api.feedback[platform]" class="platform-feedback" :class="`platform-feedback--${api.feedback[platform].type}`" role="status">{{ api.feedback[platform].message }}</p>
        <p v-else-if="status(platform).message" class="platform-note">{{ status(platform).message }}</p>
        <p v-if="status(platform).last_checked_at" class="platform-note">上次验证：{{ new Date(status(platform).last_checked_at).toLocaleString() }}</p>
      </article>
    </div>
    <details class="cookie-help"><summary>如何获取 Cookie</summary><p>在电脑浏览器登录对应平台，按 F12 打开开发者工具，在 Network（网络）中刷新页面，选择该平台的请求，复制 Request Headers 中 Cookie 的完整值后粘贴。Cookie 相当于登录凭证，请勿分享给他人。</p></details>
  </section>
</template>

<style scoped>
.platform-config { margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--border); }
.platform-heading h3 { margin: 0; font-size: 16px; }
.platform-heading p { margin: 6px 0 16px; color: var(--text-secondary); font-size: 13px; line-height: 1.5; }
.platform-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.platform-card { min-width: 0; display: flex; flex-direction: column; gap: 14px; padding: 16px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg-card); }
.platform-card__top { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.platform-card h4 { margin: 0; font-size: 15px; }
.platform-card__top p { margin: 5px 0 0; color: var(--text-secondary); font-size: 12px; }
.platform-status { padding: 4px 8px; border-radius: 6px; background: var(--bg-secondary); color: var(--text-secondary); font-size: 12px; white-space: nowrap; }
.platform-status--valid { color: #6ee7b7; }.platform-status--invalid { color: #fca5a5; }.platform-status--unknown { color: #fcd34d; }
.platform-field { display: grid; gap: 7px; color: var(--text-secondary); font-size: 12px; }
.platform-field small { color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.cookie-input { display: grid; grid-template-columns: minmax(0, 1fr) auto; }
.cookie-input input { width: 100%; min-width: 0; min-height: 44px; padding: 0 10px; border: 1px solid var(--border-hover); border-radius: 8px 0 0 8px; background: var(--bg-primary); color: var(--text-primary); font: inherit; }
.cookie-input button { min-width: 48px; border: 1px solid var(--border-hover); border-left: 0; border-radius: 0 8px 8px 0; background: var(--bg-secondary); color: var(--text-secondary); }
.platform-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.secondary-button, .ghost-button { min-height: 44px; padding: 0 12px; border: 1px solid var(--border-hover); border-radius: 8px; color: var(--text-primary); background: var(--bg-secondary); font-size: 12px; }
.ghost-button { background: transparent; }
button { cursor: pointer; }button:hover:not(:disabled) { background: var(--bg-card-hover); }button:disabled { opacity: .5; cursor: default; }
:is(input, button, summary):focus-visible { outline: 2px solid var(--accent-blue); outline-offset: 2px; }
.platform-feedback { margin: 0; font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }.platform-feedback--success { color: #6ee7b7; }.platform-feedback--error { color: #fca5a5; }.platform-feedback--warning { color: #fcd34d; }
.platform-note, .cookie-help { margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.cookie-help { margin-top: 16px; }.cookie-help summary { cursor: pointer; }.cookie-help p { margin-bottom: 0; }
.platform-loading { padding: 20px 0; color: var(--text-secondary); font-size: 13px; }
@media (max-width: 650px) { .platform-grid { grid-template-columns: 1fr; }.platform-actions > * { flex: 1; }.cookie-input input { font-size: 16px; } }
</style>
