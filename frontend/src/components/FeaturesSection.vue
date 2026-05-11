<template>
  <section class="features-section">
    <div class="features-container">
      <div class="features-header">
        <h2 class="features-title">为什么选择 SaveAny</h2>
        <p class="features-subtitle">
          强大功能，简单操作，让视频下载变得轻而易举
        </p>
      </div>

      <div class="features-grid">
        <!-- Feature 1 -->
        <div class="feature-card">
          <div class="feature-icon blue">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 class="feature-title">国内平台全覆盖</h3>
          <p class="feature-description">
            B站、抖音、小红书、快手、微博等国内主流平台，以及 YouTube、TikTok 等海外平台，粘贴链接即下载
          </p>
        </div>

        <!-- Feature 2 -->
        <div class="feature-card">
          <div class="feature-icon cyan">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <h3 class="feature-title">3 秒极速解析</h3>
          <p class="feature-description">
            基于 yt-dlp 引擎，解析速度快至 3 秒，支持多线程并发下载，速度领先同类工具
          </p>
        </div>

        <!-- Feature 3 -->
        <div class="feature-card">
          <div class="feature-icon purple">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z" />
            </svg>
          </div>
          <h3 class="feature-title">4K 高清画质</h3>
          <p class="feature-description">
            支持 4K / 1080p / 720p 多种清晰度选择，支持 MP3 音频提取，满足不同需求
          </p>
        </div>

        <!-- Feature 4 -->
        <div class="feature-card">
          <div class="feature-icon green">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 class="feature-title">永久免费</h3>
          <p class="feature-description">
            免费版永久可用，无需注册登录，无水印无广告，提供最纯净的下载体验
          </p>
        </div>

        <!-- Pro Feature 1 -->
        <div class="feature-card pro-card">
          <div class="pro-badge">Pro</div>
          <div class="feature-icon pink">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
            </svg>
          </div>
          <h3 class="feature-title">字幕翻译</h3>
          <p class="feature-description">
            自动识别视频字幕，支持中英日韩等多语言互译，一键生成双语字幕
          </p>
        </div>

        <!-- Pro Feature 2 -->
        <div class="feature-card pro-card">
          <div class="pro-badge">Pro</div>
          <div class="feature-icon orange">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
          </div>
          <h3 class="feature-title">批量下载</h3>
          <p class="feature-description">
            分P视频一键全选下载，多视频批量处理，合并导出，效率翻倍
          </p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.features-section {
  padding: 5rem 2rem;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border);
}

.features-container {
  max-width: 1200px;
  margin: 0 auto;
}

.features-header {
  text-align: center;
  margin-bottom: 4rem;
}

.features-title {
  font-size: 2.25rem;
  font-weight: 800;
  color: var(--text-primary);
  margin-bottom: 1rem;
  font-family: 'Plus Jakarta Sans', 'Noto Sans SC', sans-serif;
}

.features-subtitle {
  font-size: 1.0625rem;
  color: var(--text-secondary);
  max-width: 600px;
  margin: 0 auto;
}

.features-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.5rem;
}

.feature-card {
  position: relative;
  padding: 2rem 1.5rem;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  transition: all 0.3s;
  backdrop-filter: blur(12px);
}

.feature-card:hover {
  border-color: var(--border-hover);
  transform: translateY(-4px);
}

.feature-icon {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 1.25rem;
}

.feature-icon svg {
  width: 26px;
  height: 26px;
  color: white;
}

.feature-icon.blue {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
}

.feature-icon.cyan {
  background: linear-gradient(135deg, #06b6d4 0%, #0891b2 100%);
}

.feature-icon.purple {
  background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
}

.feature-icon.green {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
}

.feature-icon.pink {
  background: linear-gradient(135deg, #ec4899 0%, #db2777 100%);
}

.feature-icon.orange {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
}

.feature-title {
  font-size: 1.125rem;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 0.75rem;
}

.feature-description {
  font-size: 0.875rem;
  color: var(--text-secondary);
  line-height: 1.7;
}

.pro-card {
  border-color: rgba(236, 72, 153, 0.2);
}

.pro-card:hover {
  border-color: rgba(236, 72, 153, 0.4);
}

.pro-badge {
  position: absolute;
  top: 1rem;
  right: 1rem;
  padding: 0.2rem 0.625rem;
  background: linear-gradient(135deg, var(--accent-pink) 0%, #a855f7 100%);
  border-radius: 999px;
  font-size: 0.6875rem;
  font-weight: 700;
  color: white;
  letter-spacing: 0.05em;
  font-family: 'Plus Jakarta Sans', sans-serif;
}

@media (max-width: 1024px) {
  .features-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .features-section {
    padding: 3rem 1.25rem;
  }

  .features-title {
    font-size: 1.75rem;
  }

  .features-grid {
    grid-template-columns: 1fr;
  }
}
</style>
