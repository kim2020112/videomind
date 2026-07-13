import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AiSummary from './AiSummary.vue'

describe('AiSummary multipart learning state', () => {
  it('marks only parts with a current-user cache as learned', () => {
    const wrapper = mount(AiSummary, {
      props: {
        multiParts: [
          { index: 1, title: '第一节', duration: 60, is_cached: true },
          { index: 2, title: '第二节', duration: 90, is_cached: false },
        ],
        currentSummarizePart: 2,
        onSwitchPart: vi.fn(),
      },
    })

    const rows = wrapper.findAll('.part-row')
    expect(rows).toHaveLength(2)
    expect(rows[0].classes()).toContain('learned')
    expect(rows[0].get('.part-learned').text()).toContain('已学习')
    expect(rows[1].classes()).toContain('active')
    expect(rows[1].find('.part-learned').exists()).toBe(false)
  })
})
