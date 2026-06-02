<script setup>
const props = defineProps({
  url: String,
  loading: Boolean,
  onParse: Function
})

const emit = defineEmits(['update:url'])
</script>

<template>
  <section class="hero-section">
    <div class="hero-bg-glow"></div>
    <div class="hero-container">
      <h1 class="hero-title">
        <span class="hero-brand">VideoMind</span> AI 视频学习助手
      </h1>

      <p class="hero-subtitle">
        粘贴视频链接，AI 自动总结、生成结构化笔记与思维导图
      </p>

      <!-- Input and Button -->
      <div class="hero-input-section">
        <div class="input-wrapper">
          <svg class="input-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
          </svg>
          <input
            :value="url"
            @input="emit('update:url', $event.target.value)"
            @change="emit('update:url', $event.target.value)"
            type="text"
            placeholder="粘贴视频链接，支持 B站、YouTube、抖音、小红书、TikTok"
            class="hero-input"
            @keyup.enter="onParse"
          />
        </div>
        <button
          @click="onParse"
          :disabled="!url || loading"
          class="hero-parse-button"
        >
          {{ loading ? '解析中...' : '开始学习' }}
        </button>
      </div>

    </div>
  </section>
</template>

<style scoped>
.hero-section {
  position: relative;
  background: var(--bg-primary);
  padding: 5rem 2rem 4rem;
  text-align: center;
  overflow: hidden;
}

.hero-bg-glow {
  position: absolute;
  top: -40%;
  left: 50%;
  transform: translateX(-50%);
  width: 800px;
  height: 600px;
  background: radial-gradient(ellipse, rgba(59, 130, 246, 0.12) 0%, rgba(6, 182, 212, 0.06) 40%, transparent 70%);
  pointer-events: none;
}

.hero-container {
  position: relative;
  max-width: 900px;
  margin: 0 auto;
  z-index: 1;
}

.hero-title {
  font-size: 3rem;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.2;
  margin-bottom: 1rem;
  font-family: 'Plus Jakarta Sans', 'Noto Sans SC', sans-serif;
}

.hero-brand {
  background: linear-gradient(135deg, var(--accent-blue) 0%, var(--accent-cyan) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.hero-subtitle {
  font-size: 1.125rem;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 2.5rem;
}

.hero-input-section {
  display: flex;
  gap: 1rem;
  max-width: 700px;
  margin: 0 auto 1.5rem;
}

.input-wrapper {
  flex: 1;
  position: relative;
}

.input-icon {
  position: absolute;
  left: 1.25rem;
  top: 50%;
  transform: translateY(-50%);
  width: 20px;
  height: 20px;
  color: var(--text-muted);
}

.hero-input {
  width: 100%;
  padding: 1rem 1.25rem 1rem 3.25rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 0.9375rem;
  outline: none;
  transition: all 0.2s;
  background: var(--bg-card);
  color: var(--text-primary);
  backdrop-filter: blur(12px);
}

.hero-input:focus {
  border-color: var(--accent-blue);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}

.hero-input::placeholder {
  color: var(--text-muted);
}

.hero-parse-button {
  padding: 1rem 2.5rem;
  background: linear-gradient(135deg, var(--accent-blue) 0%, var(--accent-cyan) 100%);
  color: white;
  border: none;
  border-radius: var(--radius);
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.hero-parse-button:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 24px rgba(59, 130, 246, 0.3);
}

.hero-parse-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 768px) {
  .hero-section {
    padding: 2rem 1rem 1.5rem;
  }

  .hero-title {
    font-size: 1.5rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .hero-subtitle {
    font-size: 0.8125rem;
    margin-bottom: 1.25rem;
    line-height: 1.5;
  }

  .hero-input-section {
    flex-direction: column;
    gap: 0.75rem;
  }

  .hero-input {
    padding: 0.75rem 0.875rem 0.75rem 2.5rem;
    font-size: 1rem;
  }

  .input-icon {
    left: 0.75rem;
    width: 18px;
    height: 18px;
  }

  .hero-parse-button {
    width: 100%;
    padding: 0.875rem 1.5rem;
    font-size: 0.9375rem;
  }

}
</style>
