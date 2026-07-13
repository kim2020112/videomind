<script setup>
import { nextTick, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  visible: Boolean,
  titleId: { type: String, required: true },
  closeLabel: { type: String, default: '关闭弹窗' },
  initialFocus: { type: String, default: '' },
  panelClass: { type: [String, Array, Object], default: '' },
  size: { type: String, default: 'default' },
  layer: {
    type: String,
    default: 'default',
    validator: value => ['default', 'confirmation'].includes(value),
  },
  closeOnOverlay: { type: Boolean, default: true },
  showClose: { type: Boolean, default: true },
})

const emit = defineEmits(['close'])
const panelRef = ref(null)
let previousFocus = null
let previousOverflow = ''

const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function getFocusableElements() {
  if (!panelRef.value) return []
  return [...panelRef.value.querySelectorAll(focusableSelector)]
    .filter(element => element.getAttribute('aria-hidden') !== 'true')
}

function requestClose() {
  emit('close')
}

function handleOverlayClick() {
  if (props.closeOnOverlay) requestClose()
}

function handleKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    requestClose()
    return
  }
  if (event.key !== 'Tab') return

  const focusable = getFocusableElements()
  if (focusable.length === 0) {
    event.preventDefault()
    panelRef.value?.focus()
    return
  }

  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

function restorePageState() {
  document.body.style.overflow = previousOverflow
  if (previousFocus instanceof HTMLElement && document.contains(previousFocus)) {
    previousFocus.focus()
  }
  previousFocus = null
}

watch(() => props.visible, async (visible) => {
  if (visible) {
    previousFocus = document.activeElement
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    await nextTick()
    const requested = props.initialFocus
      ? panelRef.value?.querySelector(props.initialFocus)
      : null
    const target = requested || getFocusableElements()[0] || panelRef.value
    target?.focus()
  } else if (previousFocus) {
    await nextTick()
    restorePageState()
  }
}, { immediate: true })

onUnmounted(() => {
  if (previousFocus) restorePageState()
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="visible"
      class="base-dialog-overlay"
      :class="`base-dialog-overlay--${layer}`"
      @click.self="handleOverlayClick"
    >
      <div
        ref="panelRef"
        class="base-dialog-panel"
        :class="[panelClass, `base-dialog-panel--${size}`]"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        tabindex="-1"
        @keydown="handleKeydown"
      >
        <button
          v-if="showClose"
          type="button"
          class="base-dialog-close"
          :aria-label="closeLabel"
          @click="requestClose"
        >
          <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
            <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/>
          </svg>
        </button>
        <slot />
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.base-dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  background: rgba(0, 0, 0, 0.68);
  backdrop-filter: blur(6px);
  overscroll-behavior: contain;
}

.base-dialog-overlay--confirmation {
  z-index: 1100;
}

.base-dialog-panel {
  position: relative;
  width: min(100%, 420px);
  max-height: calc(100dvh - 2rem);
  overflow-y: auto;
  padding: 2rem;
  background: #1e293b;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 16px;
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.38);
  color: var(--text-primary);
  outline: none;
}

.base-dialog-panel--wide {
  width: min(100%, 680px);
}

.base-dialog-panel--video {
  width: min(100%, 1200px);
  padding: 0;
  overflow: hidden;
  background: #000;
  aspect-ratio: 16 / 9;
}

.base-dialog-close {
  position: absolute;
  top: 0.75rem;
  right: 0.75rem;
  width: 44px;
  height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.base-dialog-close:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
}

.base-dialog-close:focus-visible {
  outline: 2px solid var(--accent-blue);
  outline-offset: 2px;
}

.base-dialog-close svg {
  width: 20px;
  height: 20px;
}

@media (max-width: 480px) {
  .base-dialog-overlay {
    align-items: flex-end;
    padding: 0;
  }

  .base-dialog-panel {
    width: 100%;
    max-height: min(92dvh, 760px);
    border-radius: 18px 18px 0 0;
    padding: 1.5rem 1rem calc(1.5rem + env(safe-area-inset-bottom));
  }

  .base-dialog-panel--video {
    max-height: 100dvh;
    border-radius: 0;
    aspect-ratio: auto;
    min-height: min(56.25vw, 100dvh);
  }
}
</style>
