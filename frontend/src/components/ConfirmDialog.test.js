import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import ConfirmDialog from './ConfirmDialog.vue'


describe('ConfirmDialog', () => {
  it('uses the confirmation layer above its parent dialog', async () => {
    mount(ConfirmDialog, {
      attachTo: document.body,
      props: {
        visible: true,
        message: '确定删除？',
      },
    })
    await nextTick()

    expect(document.querySelector('.base-dialog-overlay').classList)
      .toContain('base-dialog-overlay--confirmation')
  })
})
