<script setup>
import { onMounted, onUnmounted, shallowRef } from 'vue'

const isDesktop = shallowRef(false)
let mediaQuery = null

function syncViewport(event) {
  isDesktop.value = event.matches
}

onMounted(() => {
  mediaQuery = window.matchMedia('(min-width: 1024px)')
  isDesktop.value = mediaQuery.matches
  mediaQuery.addEventListener('change', syncViewport)
})

onUnmounted(() => {
  mediaQuery?.removeEventListener('change', syncViewport)
})
</script>

<template>
  <section class="result-workspace">
    <div v-if="isDesktop" class="result-workspace__desktop">
      <slot name="desktop" />
    </div>
    <div v-else class="result-workspace__mobile">
      <slot name="mobile" />
    </div>
  </section>
</template>

<style scoped>
.result-workspace {
  padding: 3rem 2rem;
  background: var(--bg-primary);
}

@media (min-width: 1024px) {
  .result-workspace {
    padding: 2rem clamp(1.5rem, 3vw, 3rem) 3rem;
  }
}

@media (max-width: 768px) {
  .result-workspace {
    padding: 1.5rem 0.75rem;
  }
}
</style>
