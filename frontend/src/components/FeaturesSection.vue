<template>
  <section class="features-section">
    <div class="features-container">
      <div class="features-header">
        <h2 class="features-title">为什么选择 SaveAny 视频下载器</h2>
        <p class="features-subtitle">
          强大的功能，简单的操作，让视频下载变得轻而易举
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
          <h3 class="feature-title">支持1000+平台</h3>
          <p class="feature-description">
            覆盖全球主流视频平台，包括YouTube、TikTok、Bilibili、抖音、快手、小红书等
          </p>
        </div>

        <!-- Feature 2 -->
        <div class="feature-card">
          <div class="feature-icon green">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <h3 class="feature-title">极速解析下载</h3>
          <p class="feature-description">
            采用先进的解析技术，快速获取视频信息，支持多线程下载，速度更快
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
          <h3 class="feature-title">任意格式</h3>
          <p class="feature-description">
            支持多种视频格式和清晰度选择，从标清到4K，满足不同需求
          </p>
        </div>

        <!-- Feature 4 -->
        <div class="feature-card">
          <div class="feature-icon orange">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 class="feature-title">永久免费</h3>
          <p class="feature-description">
            完全免费使用，无需注册，无广告干扰，为您提供最纯净的下载体验
          </p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.features-section {
  padding: 5rem 2rem;
  background: white;
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
  font-size: 2.5rem;
  font-weight: 800;
  color: #1f2937;
  margin-bottom: 1rem;
}

.features-subtitle {
  font-size: 1.125rem;
  color: #6b7280;
  max-width: 600px;
  margin: 0 auto;
}

.features-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1.5rem;
}

.feature-card {
  padding: 2rem 1.5rem;
  background: #f9fafb;
  border-radius: 16px;
  transition: all 0.3s;
  border: 1px solid #e5e7eb;
  text-align: center;
}

.feature-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.1);
  border-color: #d1d5db;
}

.feature-icon {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 1.25rem;
}

.feature-icon svg {
  width: 28px;
  height: 28px;
  color: white;
}

.feature-icon.blue {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
}

.feature-icon.green {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
}

.feature-icon.purple {
  background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
}

.feature-icon.orange {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
}

.feature-title {
  font-size: 1.125rem;
  font-weight: 700;
  color: #1f2937;
  margin-bottom: 0.75rem;
}

.feature-description {
  font-size: 0.875rem;
  color: #6b7280;
  line-height: 1.6;
}

@media (max-width: 1024px) {
  .features-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .features-title {
    font-size: 2rem;
  }

  .features-grid {
    grid-template-columns: 1fr;
  }
}
</style>
