<script setup>
import { ref } from 'vue'
import { useAuth } from '../composables/useAuth.js'
import LoginModal from './LoginModal.vue'
import AdminSettings from './AdminSettings.vue'

defineProps({
  currentView: { type: String, default: 'home' },
  activeTaskCount: { type: Number, default: 0 }
})
const emit = defineEmits(['toggle-history', 'go-home'])

const { user, usage, isLoggedIn, isAdmin, displayName, logout } = useAuth()
const showLogin = ref(false)
const showSettings = ref(false)

async function handleLogout() {
  await logout()
  emit('logout')
  emit('go-home')
}
</script>

<template>
  <nav class="navbar">
    <div class="navbar-container">
      <!-- Logo -->
      <div class="navbar-logo" @click="$emit('go-home')" @keydown.enter="$emit('go-home')" tabindex="0" role="button">
        <div class="logo-icon">
          <svg viewBox="0 0 24 24" fill="currentColor">
            <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-8 12H9.5v-2H11v-2H9.5V9H11V7H9.5v2H8V7H6.5v2H5v2h1.5v2H5v2h1.5v2H8v-2h1.5v2H11v-2zm2.5 2H12v-2h1.5v2zm0-4H12v-2h1.5v2zm0-4H12V7h1.5v2zm4 8H16v-2h1.5v2zm0-4H16v-2h1.5v2zm0-4H16V7h1.5v2z"/>
          </svg>
        </div>
        <span class="logo-text">VideoMind</span>
      </div>

      <!-- Navigation Links -->
      <div class="navbar-links">
        <a href="#features" class="nav-link">功能特性</a>
        <a href="#tutorial" class="nav-link">使用教程</a>
      </div>

      <!-- Actions -->
      <div class="navbar-actions">
        <!-- 用量提示 -->
        <span v-if="usage.limit > 0 && usage.limit < 999999" class="usage-badge">
          AI {{ usage.used }}/{{ usage.limit }}
        </span>

        <button v-if="isLoggedIn && isAdmin" class="btn-settings" @click="showSettings = true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="btn-settings-icon">
            <path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
          </svg>
          模型配置
        </button>

        <button v-if="isLoggedIn" class="btn-history" :class="{ active: currentView === 'history' }" @click="$emit('toggle-history')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="btn-history-icon">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          学习历史
          <span v-if="activeTaskCount > 0" class="task-badge">{{ activeTaskCount }}</span>
        </button>

        <!-- 用户状态 -->
        <template v-if="isLoggedIn">
          <div class="user-menu">
            <span class="user-name">{{ displayName }}</span>
            <button class="btn-logout" @click="handleLogout" title="退出登录">
              <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 3a1 1 0 00-1 1v12a1 1 0 102 0V4a1 1 0 00-1-1zm10.293 9.293a1 1 0 001.414 1.414l3-3a1 1 0 000-1.414l-3-3a1 1 0 10-1.414 1.414L14.586 9H7a1 1 0 100 2h7.586l-1.293 1.293z" clip-rule="evenodd"/></svg>
            </button>
          </div>
        </template>
        <template v-else>
          <button class="btn-login" @click="showLogin = true">登录</button>
        </template>
      </div>
    </div>
  </nav>

  <LoginModal :visible="showLogin" @close="showLogin = false" />
  <AdminSettings :visible="showSettings" @close="showSettings = false" />
</template>

<style scoped>
.navbar {
  background: rgba(15, 23, 42, 0.8);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 100;
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
  background: linear-gradient(135deg, var(--accent-blue) 0%, var(--accent-cyan) 100%);
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
  color: var(--text-primary);
  font-family: 'Plus Jakarta Sans', sans-serif;
}

.navbar-links {
  display: flex;
  align-items: center;
  gap: 2rem;
}

.nav-link {
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 0.9375rem;
  font-weight: 500;
  transition: color 0.2s;
}

.nav-link:hover {
  color: var(--text-primary);
}

.navbar-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.usage-badge {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-muted);
  padding: 0.25rem 0.625rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border);
  border-radius: 6px;
  white-space: nowrap;
}

.btn-history {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-history:hover {
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

.btn-history.active {
  background: rgba(59, 130, 246, 0.15);
  border-color: rgba(59, 130, 246, 0.3);
  color: var(--accent-blue);
}

.btn-history-icon {
  width: 16px;
  height: 16px;
}

.task-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  background: #ef4444;
  color: white;
  font-size: 0.6875rem;
  font-weight: 700;
  border-radius: 9px;
  line-height: 1;
  animation: task-pulse 2s ease-in-out infinite;
}

@keyframes task-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.btn-settings {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-settings:hover {
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

.btn-settings-icon {
  width: 16px;
  height: 16px;
}

.user-menu {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0.75rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.user-name {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-primary);
}

.btn-logout {
  width: 24px;
  height: 24px;
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  transition: all 0.15s;
}
.btn-logout:hover { color: #fca5a5; background: rgba(239, 68, 68, 0.1); }
.btn-logout svg { width: 16px; height: 16px; }

.btn-login {
  padding: 0.5rem 1rem;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.15), rgba(6, 182, 212, 0.1));
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 8px;
  color: #93c5fd;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-login:hover {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.25), rgba(6, 182, 212, 0.2));
  border-color: rgba(59, 130, 246, 0.5);
}

@media (max-width: 768px) {
  .navbar-links {
    display: none;
  }

  .navbar-container {
    padding: 1rem;
  }

  .usage-badge { display: none; }
}
</style>
