<script setup>
defineProps({
  sidebarCollapsed: { type: Boolean, default: false },
})
</script>

<template>
  <div class="desktop-workspace" :class="{ 'desktop-workspace--collapsed': sidebarCollapsed }">
    <aside class="desktop-workspace__sidebar">
      <slot name="sidebar" />
    </aside>
    <main class="desktop-workspace__main">
      <slot name="main" />
    </main>
  </div>
</template>

<style scoped>
.desktop-workspace {
  width: min(100%, 1480px);
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(320px, 360px) minmax(0, 1fr);
  gap: 1.5rem;
  align-items: start;
  transition: grid-template-columns 0.2s ease;
}

.desktop-workspace--collapsed {
  grid-template-columns: 96px minmax(0, 1fr);
}

.desktop-workspace__sidebar {
  position: sticky;
  top: 88px;
  min-width: 0;
}

.desktop-workspace__main {
  min-width: 0;
}
</style>
