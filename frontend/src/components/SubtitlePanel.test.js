import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SubtitlePanel from './SubtitlePanel.vue'

const text = '第一句字幕。\n第二句字幕。'
const info = { source: 'bilibili_cc', language: 'zh', segments: [
  { start: 0, end: 2, text: '第一句字幕。' }, { start: 2, end: 4, text: '第二句字幕。' },
] }
const mounted = []
function panel(props = {}) {
  const wrapper = mount(SubtitlePanel, { props: { text, info, ...props }, attachTo: document.body })
  mounted.push(wrapper)
  return wrapper
}

afterEach(() => {
  mounted.splice(0).forEach(wrapper => wrapper.unmount())
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('Subtitle reading and actions', () => {
  it('opens automatically after subtitles arrive and for a newly selected video', async () => {
    const wrapper = panel({ text: '' })
    expect(wrapper.find('.subtitle-preview').exists()).toBe(false)
    await wrapper.setProps({ text })
    expect(wrapper.get('.toggle-button').attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('.subtitle-preview').text()).toContain('第一句字幕')
    await wrapper.get('.toggle-button').trigger('click')
    expect(wrapper.find('.subtitle-preview').exists()).toBe(false)
    // An unrelated progress update respects the user's manual collapse.
    await wrapper.setProps({ currentTime: 1 })
    expect(wrapper.find('.subtitle-preview').exists()).toBe(false)
    await wrapper.setProps({ title: '下一个视频', text: '新视频字幕', info: { segments: [] } })
    expect(wrapper.get('.subtitle-preview').text()).toContain('新视频字幕')
  })

  it('keeps copy and every available download accessible while collapsed', async () => {
    const wrapper = panel()
    await wrapper.get('.toggle-button').trigger('click')
    expect(wrapper.get('[aria-label="复制与下载字幕"]').findAll('button').map(button => button.text()))
      .toEqual(['复制全文', '下载 TXT', '下载 SRT', '下载 VTT'])
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    await wrapper.get('.subtitle-actions button').trigger('click')
    expect(writeText).toHaveBeenCalledWith(text)
    expect(wrapper.get('[role="status"]').text()).toContain('已复制')
  })

  it('shows format explanations only on hover or keyboard focus and dismisses with Escape', async () => {
    vi.useFakeTimers()
    const wrapper = panel()
    expect(document.querySelector('[role="tooltip"]')).toBeNull()
    const srt = wrapper.findAll('.subtitle-actions button')[2]
    await srt.trigger('mouseenter')
    let tooltip = document.querySelector('[role="tooltip"]')
    expect(tooltip.textContent).toContain('通用字幕格式')
    expect(srt.attributes('aria-describedby')).toBe(tooltip.id)
    window.dispatchEvent(new Event('scroll'))
    await wrapper.vm.$nextTick()
    expect(document.querySelector('[role="tooltip"]')).not.toBeNull()
    await srt.trigger('mouseleave')
    // Keep the explanation open when the mouse moves onto it.
    tooltip.dispatchEvent(new MouseEvent('mouseenter'))
    await vi.advanceTimersByTimeAsync(150)
    expect(document.querySelector('[role="tooltip"]')).not.toBeNull()
    tooltip.dispatchEvent(new MouseEvent('mouseleave'))
    await vi.advanceTimersByTimeAsync(150)
    expect(document.querySelector('[role="tooltip"]')).toBeNull()
    const vtt = wrapper.findAll('.subtitle-actions button')[3]
    await vtt.trigger('focus')
    tooltip = document.querySelector('[role="tooltip"]')
    expect(tooltip.textContent).toContain('网页字幕格式')
    await vtt.trigger('keydown', { key: 'Escape' })
    expect(document.querySelector('[role="tooltip"]')).toBeNull()
  })

  it('provides only plain text download when the timeline is incomplete', () => {
    const wrapper = panel({ info: { segments: [{ start: 0, text: '缺少结束时间' }] } })
    expect(wrapper.get('.subtitle-actions').findAll('button').map(button => button.text())).toEqual(['复制全文', '下载 TXT'])
    expect(wrapper.text()).toContain('无完整时间信息')
  })
  it('keeps clear accessible when collapsed and disables it during work', async () => {
    const onClear = vi.fn()
    const wrapper = panel({ onClear })
    await wrapper.get('.toggle-button').trigger('click')
    await wrapper.get('.clear-button').trigger('click')
    expect(onClear).toHaveBeenCalledOnce()
    expect(wrapper.get('.clear-button').attributes('title')).toContain('保留已整理资料')
    await wrapper.setProps({ busy: true })
    expect(wrapper.get('.clear-button').element.disabled).toBe(true)
    await wrapper.get('.clear-button').trigger('click')
    expect(onClear).toHaveBeenCalledOnce()
    await wrapper.setProps({ busy: false, text: '', info: null, cleared: true })
    expect(wrapper.text()).toContain('字幕已清空，不会自动重新获取')
    expect(wrapper.find('.clear-button').exists()).toBe(false)
    expect(wrapper.text()).toContain('获取字幕')
  })

})
