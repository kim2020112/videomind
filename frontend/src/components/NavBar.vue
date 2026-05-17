<script setup>
defineProps({
  currentView: { type: String, default: 'home' }
})
defineEmits(['toggle-history', 'go-home'])
</script>

<template>
  <nav class="navbar">
    <div class="navbar-container">
      <!-- Logo -->
      <div class="navbar-logo" @click="$emit('go-home')">
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
        <button class="btn-history" :class="{ active: currentView === 'history' }" @click="$emit('toggle-history')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="btn-history-icon">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          学习历史
        </button>
      </div>
    </div>
  </nav>
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
  gap: 1rem;
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

@media (max-width: 768px) {
  .navbar-links {
    display: none;
  }

  .navbar-container {
    padding: 1rem;
  }
}
</style>