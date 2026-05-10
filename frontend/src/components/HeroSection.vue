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
    <div class="hero-container">
      <h1 class="hero-title">
        免费在线视频下载器，<span class="hero-highlight">一键保存</span>
      </h1>

      <p class="hero-subtitle">
        支持抖音、快手、小红书、YouTube、Bilibili、TikTok、Twitter、Instagram等1000+平台
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
            placeholder="https://www.youtube.com/watch?v=... 粘贴视频链接到这里"
            class="hero-input"
            @keyup.enter="onParse"
          />
        </div>
        <button
          @click="onParse"
          :disabled="!url || loading"
          class="hero-parse-button"
        >
          {{ loading ? '解析中...' : '解析视频' }}
        </button>
      </div>

      <!-- Platform Icons -->
      <div class="platform-icons">
        <div class="platform-icon-item">
          <div class="icon-circle youtube">
            <svg viewBox="0 0 24 24" fill="currentColor">
              <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
            </svg>
          </div>
          <span>YouTube</span>
        </div>

        <div class="platform-icon-item">
          <div class="icon-circle tiktok">
            <svg viewBox="0 0 24 24" fill="currentColor">
              <path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64 2.93 2.93 0 0 1 .88.13V9.4a6.84 6.84 0 0 0-1-.05A6.33 6.33 0 0 0 5 20.1a6.34 6.34 0 0 0 10.86-4.43v-7a8.16 8.16 0 0 0 4.77 1.52v-3.4a4.85 4.85 0 0 1-1-.1z"/>
            </svg>
          </div>
          <span>TikTok</span>
        </div>

        <div class="platform-icon-item">
          <div class="icon-circle bilibili">
            <svg viewBox="0 0 24 24" fill="currentColor">
              <path d="M17.813 4.653h.854c1.51.054 2.769.578 3.773 1.574 1.004.995 1.524 2.249 1.56 3.76v7.36c-.036 1.51-.556 2.769-1.56 3.773s-2.262 1.524-3.773 1.56H5.333c-1.51-.036-2.769-.556-3.773-1.56S.036 18.858 0 17.347v-7.36c.036-1.511.556-2.765 1.56-3.76 1.004-.996 2.262-1.52 3.773-1.574h.774l-1.174-1.12a1.234 1.234 0 0 1-.373-.906c0-.356.124-.658.373-.907l.027-.027c.267-.249.573-.373.92-.373.347 0 .653.124.92.373L9.653 4.44c.071.071.134.142.187.213h4.267a.836.836 0 0 1 .16-.213l2.853-2.747c.267-.249.573-.373.92-.373.347 0 .662.151.929.4.267.249.391.551.391.907 0 .355-.124.657-.373.906zM5.333 7.24c-.746.018-1.373.276-1.88.773-.506.498-.769 1.13-.786 1.894v7.52c.017.764.28 1.395.786 1.893.507.498 1.134.756 1.88.773h13.334c.746-.017 1.373-.275 1.88-.773.506-.498.769-1.129.786-1.893v-7.52c-.017-.765-.28-1.396-.786-1.894-.507-.497-1.134-.755-1.88-.773zM8 11.107c.373 0 .684.124.933.373.25.249.383.569.4.96v1.173c-.017.391-.15.711-.4.96-.249.25-.56.374-.933.374s-.684-.125-.933-.374c-.25-.249-.383-.569-.4-.96V12.44c0-.373.129-.689.386-.947.258-.257.574-.386.947-.386zm8 0c.373 0 .684.124.933.373.25.249.383.569.4.96v1.173c-.017.391-.15.711-.4.96-.249.25-.56.374-.933.374s-.684-.125-.933-.374c-.25-.249-.383-.569-.4-.96V12.44c.017-.391.15-.711.4-.96.249-.249.56-.373.933-.373Z"/>
            </svg>
          </div>
          <span>Bilibili</span>
        </div>

        <div class="platform-icon-item">
          <div class="icon-circle douyin">
            <svg viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
            </svg>
          </div>
          <span>抖音</span>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.hero-section {
  background: linear-gradient(180deg, #f0f9ff 0%, #ffffff 100%);
  padding: 4rem 2rem 5rem;
  text-align: center;
}

.hero-container {
  max-width: 900px;
  margin: 0 auto;
}

.hero-title {
  font-size: 2.75rem;
  font-weight: 800;
  color: #1f2937;
  line-height: 1.3;
  margin-bottom: 1.25rem;
}

.hero-highlight {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.hero-subtitle {
  font-size: 1rem;
  color: #6b7280;
  line-height: 1.6;
  margin-bottom: 2.5rem;
  max-width: 700px;
  margin-left: auto;
  margin-right: auto;
}

.hero-input-section {
  display: flex;
  gap: 1rem;
  max-width: 700px;
  margin: 0 auto 3rem;
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
  color: #9ca3af;
}

.hero-input {
  width: 100%;
  padding: 1rem 1.25rem 1rem 3.25rem;
  border: 2px solid #e5e7eb;
  border-radius: 12px;
  font-size: 0.9375rem;
  outline: none;
  transition: all 0.2s;
  background: white;
}

.hero-input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.hero-input::placeholder {
  color: #9ca3af;
}

.hero-parse-button {
  padding: 1rem 2.5rem;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: white;
  border: none;
  border-radius: 12px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
}

.hero-parse-button:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(59, 130, 246, 0.4);
}

.hero-parse-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.platform-icons {
  display: flex;
  justify-content: center;
  gap: 3rem;
  flex-wrap: wrap;
}

.platform-icon-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
}

.icon-circle {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.3s;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.icon-circle:hover {
  transform: translateY(-4px);
}

.icon-circle svg {
  width: 28px;
  height: 28px;
  color: white;
}

.youtube {
  background: linear-gradient(135deg, #ff0000 0%, #cc0000 100%);
}

.tiktok {
  background: linear-gradient(135deg, #000000 0%, #333333 100%);
}

.bilibili {
  background: linear-gradient(135deg, #00a1d6 0%, #0084b4 100%);
}

.douyin {
  background: linear-gradient(135deg, #fe2c55 0%, #d91a3f 100%);
}

.platform-icon-item span {
  font-size: 0.8125rem;
  color: #6b7280;
  font-weight: 500;
}

@media (max-width: 768px) {
  .hero-title {
    font-size: 2rem;
  }

  .hero-subtitle {
    font-size: 0.9375rem;
  }

  .hero-input-section {
    flex-direction: column;
  }

  .platform-icons {
    gap: 2rem;
  }

  .icon-circle {
    width: 48px;
    height: 48px;
  }

  .icon-circle svg {
    width: 24px;
    height: 24px;
  }
}
</style>