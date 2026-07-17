import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { nextTick, reactive } from 'vue'
import ConnectionForm from './ConnectionForm.vue'

const pending = reactive({ save: false, discover: false })

function model(id, overrides = {}) {
  return {
    id,
    name: id,
    model: `upstream-${id}`,
    source: 'discovered',
    discovery_status: 'not_returned',
    test_status: 'untested',
    test_message: '',
    tested_at: '',
    ...overrides,
  }
}

function connection() {
  return {
    id: 'c1',
    name: 'Gateway',
    api_format: 'openai',
    base_url: 'https://gateway.example.com/v1',
    models_url: '',
    discovery_url: '',
    primary_model_id: 'manual',
    models: [
      model('manual', { source: 'manual', discovery_status: 'manual' }),
      model('known', { test_status: 'failed', test_message: 'blocked', tested_at: '2026-07-17T00:00:00Z' }),
    ],
  }
}

afterEach(() => {
  document.body.innerHTML = ''
})

describe('ConnectionForm', () => {
  it('merges discovery into the full catalog without replacing the primary or test results', async () => {
    const wrapper = mount(ConnectionForm, {
      props: { connection: connection(), pending },
    })

    await wrapper.setProps({
      discoveryResult: {
        base_url: 'https://gateway.example.com/v1',
        models_url: '',
        discovery_url: 'https://gateway.example.com/v1/models',
        models: [
          { name: 'Known now', model: 'upstream-known' },
          { name: 'New', model: 'upstream-new' },
        ],
      },
    })
    await nextTick()

    const select = wrapper.get('select[name="primary_model"]')
    expect(select.element.value).toBe('manual')
    expect(wrapper.findAll('option').map(option => option.text())).toEqual(expect.arrayContaining([
      expect.stringContaining('upstream-manual'),
      expect.stringContaining('upstream-known'),
      expect.stringContaining('upstream-new'),
    ]))

    await wrapper.get('form').trigger('submit')
    const payload = wrapper.emitted('save')[0][0]
    const known = payload.models.find(item => item.id === 'known')
    expect(payload.primary_model).toBe('manual')
    expect(known.discovery_status).toBe('available')
    expect(known.test_status).toBe('failed')
    expect(known.test_message).toBe('blocked')
  })

  it('automatically selects a manually added model', async () => {
    const wrapper = mount(ConnectionForm, { props: { connection: connection(), pending } })
    const input = wrapper.get('input[name="manual_model"]')

    await input.setValue('custom-model')
    await input.trigger('keydown', { key: 'Enter' })
    await wrapper.get('form').trigger('submit')

    const payload = wrapper.emitted('save')[0][0]
    const added = payload.models.find(item => item.model === 'custom-model')
    expect(added).toMatchObject({ source: 'manual', discovery_status: 'manual', test_status: 'untested' })
    expect(payload.primary_model).toBe(added.id)
  })

  it('renders identical model names and ids only once', () => {
    const configured = connection()
    configured.models.push(model('deepseek', {
      name: 'deepseek-v4-flash',
      model: 'deepseek-v4-flash',
    }))
    const wrapper = mount(ConnectionForm, {
      props: { connection: configured, pending },
    })

    expect(wrapper.get('option[value="deepseek"]').text()).toBe('deepseek-v4-flash')
  })

  it('focuses the first invalid field and reports dirty changes', async () => {
    const wrapper = mount(ConnectionForm, {
      attachTo: document.body,
      props: { connection: null, pending },
    })

    await wrapper.get('form').trigger('submit')
    await nextTick()
    expect(document.activeElement).toBe(wrapper.get('input[name="connection_name"]').element)

    await wrapper.get('input[name="connection_name"]').setValue('New gateway')
    expect(wrapper.emitted('dirtyChange').at(-1)).toEqual([true])
    wrapper.unmount()
  })
})
