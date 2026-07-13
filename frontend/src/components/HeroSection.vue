<script setup>
import { computed } from 'vue'

const props = defineProps({
  url: { type: String, default: '' },
  loading: Boolean,
  requiresLogin: Boolean,
  serviceChecking: Boolean,
  compact: Boolean,
  serviceError: { type: String, default: '' },
})

const emit = defineEmits(['update:url', 'parse', 'request-login', 'retry-capabilities'])

const buttonLabel = computed(() => {
  if (props.loading) return '解析中…'
  if (props.serviceChecking) return '检查服务中…'
  if (props.requiresLogin) return '登录后开始'
  return '开始学习'
})

function submit() {
  if (!props.url.trim() || props.loading || props.serviceChecking) return
  if (props.requiresLogin) {
    emit('request-login')
  } else {
    emit('parse')
  }
}
</script>

<template>
  <section class="hero-section" :class="{ 'hero-section--compact': compact }">
    <div class="hero-bg-glow"></div>
    <div class="hero-container">
      <div v-if="!compact" class="hero-copy">
        <h1 class="hero-title">
          <span class="hero-brand">VideoMind</span> AI 视频学习助手
        </h1>
        <p class="hero-subtitle">粘贴视频链接，AI 自动总结、生成结构化笔记与思维导图</p>
      </div>

      <form class="hero-input-section" @submit.prevent="submit">
        <div class="input-wrapper">
          <label class="sr-only" for="video-url-input">视频链接</label>
          <svg class="input-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
          </svg>
          <input
            id="video-url-input"
            :value="url"
            name="video-url"
            type="url"
            inputmode="url"
            autocomplete="off"
            spellcheck="false"
            placeholder="粘贴视频链接，例如 https://www.bilibili.com/video/…"
            class="hero-input"
            @input="emit('update:url', $event.target.value)"
            @change="emit('update:url', $event.target.value)"
            @keydown.enter.prevent="submit"
          />
        </div>
        <button type="button" :disabled="!url.trim() || loading || serviceChecking" class="hero-parse-button" @click="submit">
          {{ buttonLabel }}
        </button>
      </form>

      <div v-if="serviceError" class="hero-service-error" role="status">
        <span>{{ serviceError }}</span>
        <button type="button" @click="emit('retry-capabilities')">重新检测</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.hero-section {
  position: relative;
  overflow: hidden;
  padding: 5rem 2rem 4rem;
  background: var(--bg-primary);
  text-align: center;
  transition: padding 0.2s ease, border-color 0.2s ease;
}

.hero-section--compact {
  padding: 1rem clamp(0.75rem, 3vw, 3rem);
  border-bottom: 1px solid var(--border);
  text-align: left;
}

.hero-bg-glow {
  position: absolute;
  top: -40%;
  left: 50%;
  width: 800px;
  height: 600px;
  transform: translateX(-50%);
  background: radial-gradient(ellipse, rgba(59, 130, 246, 0.12) 0%, rgba(6, 182, 212, 0.06) 40%, transparent 70%);
  pointer-events: none;
}

.hero-section--compact .hero-bg-glow {
  width: 520px;
  height: 220px;
}

.hero-container {
  position: relative;
  z-index: 1;
  max-width: 900px;
  margin: 0 auto;
}

.hero-section--compact .hero-container {
  max-width: 1480px;
}

.hero-title {
  margin-bottom: 1rem;
  color: var(--text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  font-size: 3rem;
  font-weight: 800;
  line-height: 1.2;
  text-wrap: balance;
}

.hero-brand {
  background: linear-gradient(135deg, var(--accent-blue) 0%, var(--accent-cyan) 100%);
  background-clip: text;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero-subtitle {
  margin: 0 auto 2.5rem;
  color: var(--text-secondary);
  font-size: 1.125rem;
  line-height: 1.6;
  text-wrap: pretty;
}

.hero-input-section {
  display: flex;
  gap: 0.75rem;
  width: 100%;
  max-width: 800px;
  margin: 0 auto;
}

.hero-section--compact .hero-input-section {
  max-width: none;
}

.input-wrapper {
  position: relative;
  flex: 1;
}

.input-icon {
  position: absolute;
  top: 50%;
  left: 1.25rem;
  width: 20px;
  height: 20px;
  transform: translateY(-50%);
  color: var(--text-muted);
  pointer-events: none;
}

.hero-input {
  width: 100%;
  min-height: 54px;
  padding: 1rem 1.25rem 1rem 3.25rem;
  border: 1px solid var(--border-hover);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary);
  font-size: 1rem;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
}

.hero-section--compact .hero-input {
  min-height: 48px;
  padding-top: 0.75rem;
  padding-bottom: 0.75rem;
}

.hero-input:focus-visible {
  border-color: var(--accent-blue);
  background: rgba(255, 255, 255, 0.07);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
}

.hero-input::placeholder {
  color: var(--text-muted);
}

.hero-parse-button {
  min-height: 54px;
  padding: 1rem 2.5rem;
  border: 0;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--accent-blue) 0%, var(--accent-cyan) 100%);
  color: white;
  font-size: 1rem;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}

.hero-section--compact .hero-parse-button {
  min-height: 48px;
  padding: 0.75rem 1.5rem;
}

.hero-parse-button:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 24px rgba(59, 130, 246, 0.3);
}

.hero-parse-button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.hero-service-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  margin-top: 0.75rem;
  color: #fca5a5;
  font-size: 0.8125rem;
}

.hero-service-error button {
  min-height: 36px;
  padding: 0.375rem 0.75rem;
  border: 1px solid rgba(248, 113, 113, 0.35);
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.08);
  color: #fecaca;
  cursor: pointer;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 768px) {
  .hero-section {
    padding: 3.25rem 1rem 2.75rem;
  }

  .hero-section--compact {
    padding: 0.75rem;
  }

  .hero-title {
    font-size: 2rem;
  }

  .hero-subtitle {
    margin-bottom: 2rem;
    font-size: 1rem;
  }

  .hero-input-section {
    flex-direction: column;
  }

  .hero-parse-button {
    width: 100%;
    min-height: 50px;
    padding: 0.875rem 1.5rem;
  }

  .hero-section--compact .hero-input-section {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .hero-section--compact .hero-parse-button {
    width: auto;
    min-width: 112px;
  }
}

@media (max-width: 520px) {
  .hero-section--compact .hero-input-section {
    grid-template-columns: 1fr;
  }

  .hero-section--compact .hero-parse-button {
    width: 100%;
  }
}
</style>
