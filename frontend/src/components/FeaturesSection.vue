<template>
  <section id="features" class="features-section">
    <div class="features-container">
      <div class="features-header">
        <h2 class="features-title">让视频成为你的知识库</h2>
        <p class="features-subtitle">
          AI 驱动的内容理解，将任何视频转化为可检索、可回顾的结构化知识
        </p>
      </div>

      <div class="features-grid">
        <!-- Feature 1 -->
        <div class="feature-card">
          <div class="feature-icon blue">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
          </div>
          <h3 class="feature-title">AI 智能总结</h3>
          <p class="feature-description">
            自动提取视频字幕，大模型生成精炼摘要，快速把握核心内容
          </p>
        </div>

        <!-- Feature 2 -->
        <div class="feature-card">
          <div class="feature-icon cyan">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
            </svg>
          </div>
          <h3 class="feature-title">结构化学习笔记</h3>
          <p class="feature-description">
            自动生成标题层级分明的 Markdown 笔记，支持代码块、重点高亮，一键导出
          </p>
        </div>

        <!-- Feature 3 -->
        <div class="feature-card">
          <div class="feature-icon purple">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
            </svg>
          </div>
          <h3 class="feature-title">思维导图</h3>
          <p class="feature-description">
            自动提炼关键概念生成思维导图，支持 SVG/PNG 导出和全屏浏览
          </p>
        </div>

        <!-- Feature 4 -->
        <div class="feature-card">
          <div class="feature-icon green">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
            </svg>
          </div>
          <h3 class="feature-title">AI 问答</h3>
          <p class="feature-description">
            基于视频字幕内容的智能问答，想问什么直接问，AI 帮你找答案
          </p>
        </div>

        <!-- Feature 5 -->
        <div class="feature-card">
          <div class="feature-icon pink">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
            </svg>
          </div>
          <h3 class="feature-title">字幕提取与翻译</h3>
          <p class="feature-description">
            自动获取视频字幕，支持 SRT/VTT/TXT 格式下载，多语言互译
          </p>
        </div>

        <!-- Feature 6 -->
        <div class="feature-card">
          <div class="feature-icon orange">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5m8.25 3v6.75m0 0l-3-3m3 3l3-3M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
            </svg>
          </div>
          <h3 class="feature-title">学习历史</h3>
          <p class="feature-description">
            自动保存每次 AI 分析结果，随时回顾已学视频的知识点
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
