import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import BaseDialog from './BaseDialog.vue'

function mountDialog({ visible = false } = {}) {
  const trigger = document.createElement('button')
  trigger.textContent = '打开'
  document.body.appendChild(trigger)
  trigger.focus()

  const wrapper = mount(BaseDialog, {
    attachTo: document.body,
    props: {
      visible,
      titleId: 'dialog-title',
      closeLabel: '关闭测试弹窗',
      initialFocus: '[data-initial-focus]',
    },
    slots: {
      default: `
        <h2 id="dialog-title">测试弹窗</h2>
        <input data-initial-focus />
        <button data-last-action>保存</button>
      `,
    },
  })

  return { wrapper, trigger }
}

describe('BaseDialog', () => {
  it('locks scrolling and focuses when initially mounted visible', async () => {
    const { wrapper } = mountDialog({ visible: true })
    await nextTick()

    expect(document.body.style.overflow).toBe('hidden')
    expect(document.activeElement.matches('[data-initial-focus]')).toBe(true)
    wrapper.unmount()
  })

  it('sets dialog semantics, locks scrolling and focuses the requested control', async () => {
    const { wrapper } = mountDialog()

    await wrapper.setProps({ visible: true })
    await nextTick()

    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog).not.toBeNull()
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(dialog.getAttribute('aria-labelledby')).toBe('dialog-title')
    expect(document.body.style.overflow).toBe('hidden')
    expect(document.activeElement.matches('[data-initial-focus]')).toBe(true)
    expect(document.querySelector('.base-dialog-close').getAttribute('aria-label')).toBe('关闭测试弹窗')
  })

  it('traps Tab focus and closes on Escape', async () => {
    const { wrapper } = mountDialog()
    await wrapper.setProps({ visible: true })
    await nextTick()

    const dialog = document.querySelector('[role="dialog"]')
    const closeButton = document.querySelector('.base-dialog-close')
    const lastButton = document.querySelector('[data-last-action]')

    lastButton.focus()
    dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    expect(document.activeElement).toBe(closeButton)

    closeButton.focus()
    dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true }))
    expect(document.activeElement).toBe(lastButton)

    dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('restores body overflow and trigger focus after closing', async () => {
    const { wrapper, trigger } = mountDialog()
    await wrapper.setProps({ visible: true })
    await nextTick()
    expect(document.activeElement).not.toBe(trigger)

    await wrapper.setProps({ visible: false })
    await nextTick()

    expect(document.body.style.overflow).toBe('')
    expect(document.activeElement).toBe(trigger)
  })
})
