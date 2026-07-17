import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ConnectionItem from './ConnectionItem.vue'

function connection() {
  return {
    id: 'c1',
    name: 'Gateway',
    api_format: 'openai',
    api_key: '******cret',
    base_url: 'https://gateway.example.com/v1',
    primary_model_id: 'm1',
    models: [
      { id: 'm1', name: 'One', model: 'model-one', discovery_status: 'available', test_status: 'passed' },
      { id: 'm2', name: 'Two', model: 'model-two', discovery_status: 'not_returned', test_status: 'failed' },
    ],
  }
}

function props(overrides = {}) {
  return {
    connection: connection(),
    active: { connection_id: 'other', model_id: 'other-model' },
    pending: { refresh: {}, test: {}, switch: '', delete: '' },
    connectionFeedback: null,
    modelFeedback: {},
    ...overrides,
  }
}

describe('ConnectionItem', () => {
  it('always displays the connections saved primary model and split statuses', async () => {
    const wrapper = mount(ConnectionItem, { props: props() })
    expect(wrapper.get('.current-model').text()).toBe('model-one')

    await wrapper.get('.summary').trigger('click')
    expect(wrapper.text()).toContain('已发现')
    expect(wrapper.text()).toContain('测试通过')
  })

  it('rolls the select back after a failed switch finishes', async () => {
    const wrapper = mount(ConnectionItem, { props: props() })
    await wrapper.get('.summary').trigger('click')
    const select = wrapper.get('select[name="primary_model"]')

    await select.setValue('m2')
    expect(wrapper.emitted('switch')[0]).toEqual(['c1', 'm2'])
    await wrapper.setProps({ pending: { refresh: {}, test: {}, switch: 'c1', delete: '' } })
    await wrapper.setProps({
      pending: { refresh: {}, test: {}, switch: '', delete: '' },
      connectionFeedback: { action: 'switch', type: 'error', message: '切换失败' },
    })

    expect(wrapper.get('select[name="primary_model"]').element.value).toBe('m1')
    expect(wrapper.text()).toContain('切换失败')
  })

  it('shows persisted failure only as a status and clears transient details when collapsed', async () => {
    const failedConnection = connection()
    Object.assign(failedConnection.models[0], {
      name: 'deepseek-v4-flash',
      model: 'deepseek-v4-flash',
      test_status: 'failed',
      test_message: 'API 响应中未找到文本内容',
    })
    const wrapper = mount(ConnectionItem, {
      props: props({ connection: failedConnection }),
    })

    await wrapper.get('.summary').trigger('click')
    expect(wrapper.text()).toContain('测试失败')
    expect(wrapper.text()).not.toContain('API 响应中未找到文本内容')
    expect(wrapper.get('.model-status--test-failed').attributes('title')).toBeUndefined()
    expect(wrapper.get('option[value="m1"]').text()).toBe('deepseek-v4-flash')

    await wrapper.setProps({
      modelFeedback: {
        'c1:m1': { type: 'error', message: 'API 响应中未找到文本内容' },
      },
    })
    expect(wrapper.text()).toContain('API 响应中未找到文本内容')

    await wrapper.get('.summary').trigger('click')
    expect(wrapper.emitted('clear-model-feedback')).toEqual([['c1:m1']])

    await wrapper.setProps({ modelFeedback: {} })
    await wrapper.get('.summary').trigger('click')
    expect(wrapper.text()).toContain('测试失败')
    expect(wrapper.text()).not.toContain('API 响应中未找到文本内容')
  })
})
