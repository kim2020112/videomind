import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import TaskProgressDock from './TaskProgressDock.vue'

describe('TaskProgressDock', () => {
  it('summarizes active tasks and opens history', async () => {
    const wrapper = mount(TaskProgressDock, {
      props: {
        tasks: [
          { task_id: 'one', status: 'transcribing', progress: 42, message: '正在转录' },
          { task_id: 'two', status: 'queued', progress: 0 },
        ],
      },
    })

    expect(wrapper.text()).toContain('2 个后台任务')
    expect(wrapper.text()).toContain('42%')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('open-history')).toHaveLength(1)
  })

  it('renders nothing without active tasks', () => {
    const wrapper = mount(TaskProgressDock, { props: { tasks: [] } })
    expect(wrapper.find('button').exists()).toBe(false)
  })
})
