<template>
  <footer class="footer">
    <div class="footer-container">
      <div class="footer-top">
        <div class="footer-brand">
          <div class="footer-logo">
            <div class="logo-icon">
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-8 12H9.5v-2H11v-2H9.5V9H11V7H9.5v2H8V7H6.5v2H5v2h1.5v2H5v2h1.5v2H8v-2h1.5v2H11v-2zm2.5 2H12v-2h1.5v2zm0-4H12v-2h1.5v2zm0-4H12V7h1.5v2zm4 8H16v-2h1.5v2zm0-4H16v-2h1.5v2zm0-4H16V7h1.5v2z"/>
              </svg>
            </div>
            <span class="footer-logo-text">VideoMind</span>
          </div>
          <p class="footer-desc">
            AI 视频学习助手 — 将视频转化为结构化知识，支持 B站、YouTube、抖音、小红书、TikTok。
          </p>
        </div>

        <div class="footer-links">
          <div class="footer-link-group">
            <h4 class="footer-link-title">功能</h4>
            <a href="#features" class="footer-link">AI 总结</a>
            <a href="#features" class="footer-link">学习笔记</a>
            <a href="#features" class="footer-link">思维导图</a>
          </div>
        </div>
      </div>

      <div class="footer-bottom">
        <span class="footer-copyright">&copy; 2026 VideoMind</span>
      </div>
    </div>
  </footer>
</template>

<style scoped>
.footer {
  background: var(--bg-primary);
  border-top: 1px solid var(--border);
  padding: 3rem 2rem 2rem;
}

.footer-container {
  max-width: 1200px;
  margin: 0 auto;
}

.footer-top {
  display: flex;
  justify-content: space-between;
  gap: 4rem;
  margin-bottom: 2.5rem;
}

.footer-brand {
  max-width: 300px;
}

.footer-logo {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  margin-bottom: 0.875rem;
}

.logo-icon {
  width: 28px;
  height: 28px;
  background: linear-gradient(135deg, var(--accent-blue) 0%, var(--accent-cyan) 100%);
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.logo-icon svg {
  width: 18px;
  height: 18px;
}

.footer-logo-text {
  font-size: 1.125rem;
  font-weight: 700;
  color: var(--text-primary);
  font-family: 'Plus Jakarta Sans', sans-serif;
}

.footer-desc {
  font-size: 0.875rem;
  color: var(--text-muted);
  line-height: 1.7;
}

.footer-links {
  display: flex;
  gap: 4rem;
}

.footer-link-group {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

.footer-link-title {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 0.375rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.footer-link {
  font-size: 0.875rem;
  color: var(--text-muted);
  transition: color 0.2s;
}

.footer-link:hover {
  color: var(--text-primary);
}

.footer-bottom {
  display: flex;
  justify-content: center;
}

.footer-copyright {
  font-size: 0.8125rem;
  color: var(--text-muted);
}

@media (max-width: 768px) {
  .footer {
    padding: 2rem 1.25rem 1.5rem;
  }

  .footer-top {
    flex-direction: column;
    gap: 2rem;
  }

  .footer-brand {
    max-width: 100%;
  }

  .footer-links {
    gap: 2rem;
    flex-wrap: wrap;
  }

}
</style>
