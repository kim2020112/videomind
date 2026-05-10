<template>
  <nav class="navbar">
    <div class="navbar-container">
      <!-- Logo -->
      <div class="navbar-logo">
        <div class="logo-icon">
          <svg viewBox="0 0 24 24" fill="currentColor">
            <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-8 12H9.5v-2H11v-2H9.5V9H11V7H9.5v2H8V7H6.5v2H5v2h1.5v2H5v2h1.5v2H8v-2h1.5v2H11v-2zm2.5 2H12v-2h1.5v2zm0-4H12v-2h1.5v2zm0-4H12V7h1.5v2zm4 8H16v-2h1.5v2zm0-4H16v-2h1.5v2zm0-4H16V7h1.5v2z"/>
          </svg>
        </div>
        <span class="logo-text">SaveAny</span>
      </div>

      <!-- Navigation Links -->
      <div class="navbar-links">
        <a href="#features" class="nav-link">功能特性</a>
        <a href="#tutorial" class="nav-link">使用教程</a>
        <a href="#tools" class="nav-link">工具箱</a>
        <a href="#faq" class="nav-link">常见问题</a>
      </div>

      <!-- Actions -->
      <div class="navbar-actions">
        <button class="btn-login">登录</button>
        <button class="btn-start">立即使用</button>
      </div>
    </div>
  </nav>
</template>

<style scoped>
.navbar {
  background: white;
  border-bottom: 1px solid #e5e7eb;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.navbar-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1rem 2rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.navbar-logo {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  cursor: pointer;
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.logo-icon svg {
  width: 20px;
  height: 20px;
}

.logo-text {
  font-size: 1.25rem;
  font-weight: 700;
  color: #1f2937;
}

.navbar-links {
  display: flex;
  align-items: center;
  gap: 2rem;
}

.nav-link {
  color: #6b7280;
  text-decoration: none;
  font-size: 0.9375rem;
  font-weight: 500;
  transition: color 0.2s;
}

.nav-link:hover {
  color: #3b82f6;
}

.navbar-actions {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.btn-login {
  padding: 0.5rem 1.25rem;
  background: transparent;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  color: #374151;
  font-size: 0.9375rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-login:hover {
  background: #f9fafb;
  border-color: #d1d5db;
}

.btn-start {
  padding: 0.5rem 1.25rem;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 0.9375rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);
}

.btn-start:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4);
}

@media (max-width: 768px) {
  .navbar-links {
    display: none;
  }

  .navbar-container {
    padding: 1rem;
  }
}
</style>