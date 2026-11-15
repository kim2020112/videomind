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
    expect(rows[0].get('.part-learned').text()).toContain('已整理')
    expect(rows[1].classes()).toContain('active')
    expect(rows[1].find('.part-learned').exists()).toBe(false)
  })
})

describe('shared module toolbar', () => {
  it('keeps saved QA readable after clearing subtitles and toggles all through the owner', async () => {
    const toggle = vi.fn()
    const wrapper = mount(AiSummary, { props: { workspaceMode: true, subtitleText: '',
      qaPairs: [{ question: '问题', answer: '保留的回答', expanded: false }], onToggleQaExpand: toggle } })
    await wrapper.findAll('.sub-tab-btn').find(b => b.text() === '精选问答').trigger('click')
    expect(wrapper.find('.qa-pairs-list').isVisible()).toBe(true)
    await wrapper.findAll('.module-toolbar button').find(b => b.text() === '全部展开').trigger('click')
    expect(toggle).toHaveBeenCalledWith(0)
    wrapper.unmount()
  })
  it('copies saved summary during generation and keeps generation locked at the top', async () => {
    const copy = vi.fn().mockResolvedValue()
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: copy } })
    const regenerate = vi.fn()
    const wrapper = mount(AiSummary, { props: { workspaceMode: true, loading: true,
      result: { summary: '已有摘要' }, onRegenerateSummary: regenerate } })
    const toolbar = wrapper.get('.module-toolbar')
    await toolbar.findAll('button').find(b => b.text() === '复制').trigger('click')
    expect(copy).toHaveBeenCalledWith('已有摘要')
    expect(toolbar.findAll('button').find(b => b.text() === '重新生成摘要').element.disabled).toBe(true)
    expect(wrapper.find('.summary-scroll .regenerate-btn').exists()).toBe(false)
    wrapper.unmount()
  })
})
