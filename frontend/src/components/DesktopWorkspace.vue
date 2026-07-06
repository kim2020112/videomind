<template>
  <div class="desktop-workspace">
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
  gap: 1.25rem;
  align-items: start;
}

.desktop-workspace__sidebar {
  position: sticky;
  top: 88px;
}

.desktop-workspace__main {
  min-width: 0;
}
</style>
