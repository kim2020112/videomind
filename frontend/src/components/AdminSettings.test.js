import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import AdminSettings from './AdminSettings.vue'
import ConnectionForm from './ai-config/ConnectionForm.vue'

function response(data, ok = true) {
  return { ok, json: vi.fn().mockResolvedValue(data) }
}

function connection() {
  return {
    id: 'c1',
    name: 'Gateway',
    api_format: 'openai',
    api_key: '******cret',
    base_url: 'https://gateway.example.com/v1',
    models_url: '',
    discovery_url: '',
    primary_model_id: 'm1',
    models: [{
      id: 'm1',
      name: 'Model',
      model: 'model-1',
      source: 'discovered',
      discovery_status: 'available',
      test_status: 'untested',
      test_message: '',
      tested_at: '',
    }],
  }
}

afterEach(() => {
  vi.restoreAllMocks()
  document.body.innerHTML = ''
  document.body.style.overflow = ''
})

async function openSettings(fetchResponse) {
  global.fetch = vi.fn().mockResolvedValue(fetchResponse)
  const wrapper = mount(AdminSettings, {
    attachTo: document.body,
    props: { visible: false },
  })
  await wrapper.setProps({ visible: true })
  await flushPromises()
  return wrapper
}

describe('AdminSettings', () => {
  it('routes Escape through discard confirmation when the form is dirty', async () => {
    const wrapper = await openSettings(response({ connections: [], active: {} }))
    document.querySelector('.add-button').click()
    await nextTick()

    const form = wrapper.getComponent(ConnectionForm)
    await form.get('input[name="connection_name"]').setValue('Unsaved gateway')
    document.querySelector('#ai-settings-title').closest('[role="dialog"]')
      .dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await nextTick()

    expect(document.body.textContent).toContain('放弃未保存的修改？')
    expect(wrapper.emitted('close')).toBeUndefined()

    document.querySelector('.base-dialog-overlay--confirmation .confirm-button--danger').click()
    await nextTick()
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })

  it('keeps delete confirmation open while pending and shows failure in place', async () => {
    let resolveDelete
    const deleteRequest = new Promise(resolve => { resolveDelete = resolve })
    const configured = connection()
    const wrapper = await openSettings(response({
      connections: [configured],
      active: { connection_id: 'c1', model_id: 'm1' },
    }))
    global.fetch.mockReturnValueOnce(deleteRequest)

    document.querySelector('.icon-button.danger').click()
    await nextTick()
    document.querySelector('.base-dialog-overlay--confirmation .confirm-button--danger').click()
    await nextTick()

    const confirmation = document.querySelector('.base-dialog-overlay--confirmation')
    expect(confirmation.textContent).toContain('删除中...')
    expect(confirmation.querySelector('.base-dialog-close')).toBeNull()

    resolveDelete(response({ detail: '连接仍被任务使用' }, false))
    await flushPromises()

    expect(document.querySelector('.base-dialog-overlay--confirmation')).not.toBeNull()
    expect(document.body.textContent).toContain('连接仍被任务使用')
    expect(document.querySelector('.base-dialog-overlay--confirmation .confirm-button--danger').textContent).toContain('删除')
    wrapper.unmount()
  })
})
