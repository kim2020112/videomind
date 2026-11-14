import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import LearningWorkspace from './LearningWorkspace.vue'
import SubtitlePanel from './SubtitlePanel.vue'

const base = { qaPairs: [], chatMessages: [], moduleStates: {}, selectedTargets: ['summary', 'mindmap', 'notes', 'qa'] }
function mountWorkspace(props = {}) {
  return mount(LearningWorkspace, { props: { ...base, ...props }, global: { stubs: { AiSummary: true } } })
}

describe('Learning workspace', () => {
  it('offers subtitle access before any AI result and sends only selected modules', async () => {
    const fetch = vi.fn()
    const generate = vi.fn()
    const wrapper = mountWorkspace({ onFetchSubtitle: fetch, onGenerateTargets: generate, selectedTargets: ['mindmap'] })
    expect(wrapper.find('h2').text()).toBe('字幕与转录')
    await wrapper.findComponent(SubtitlePanel).find('button').trigger('click')
    expect(fetch).toHaveBeenCalledWith(false)
    await wrapper.find('.generate-button').trigger('click')
    expect(generate).toHaveBeenCalledWith(['mindmap'])
    wrapper.unmount()
  })

  it('opens saved subtitles by default and keeps downloads visible when collapsed', async () => {
    const wrapper = mountWorkspace({ subtitleText: '第一行字幕\n第二行字幕', subtitleInfo: { source: 'bilibili_cc', language: 'ai-zh', segments: [] } })
    const panel = wrapper.findComponent(SubtitlePanel)
    expect(panel.text()).toContain('B站 CC · 简体中文 · 自动')
    expect(panel.find('.subtitle-preview').exists()).toBe(true)
    expect(panel.text()).toContain('下载 TXT')
    await panel.get('.toggle-button').trigger('click')
    expect(panel.find('.subtitle-preview').exists()).toBe(false)
    expect(panel.text()).toContain('复制全文')
    expect(panel.text()).toContain('下载 TXT')
    wrapper.unmount()
  })

  it('requires an explicit click to resume transcription and retains target selection', async () => {
    const resume = vi.fn()
    const wrapper = mountWorkspace({ backgroundTask: { status: 'awaiting_confirmation', estimated_seconds: 120, payload: { targets: ['notes'] } }, onResumeTask: resume })
    expect(resume).not.toHaveBeenCalled()
    expect(wrapper.find('.learning-task').text()).toContain('2 分钟')
    await wrapper.findAll('button').find(b => b.text() === '开始语音转录').trigger('click')
    expect(resume).toHaveBeenCalledOnce()
    expect(wrapper.find('.generate-button').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('offers independent retry without losing successful modules', async () => {
    const generate = vi.fn()
    const wrapper = mountWorkspace({ moduleStates: { summary: { status: 'failed', error: '模型超时' }, mindmap: { status: 'done' } }, onGenerateTargets: generate })
    expect(wrapper.text()).toContain('模型超时')
    expect(wrapper.text()).toContain('已完成')
    await wrapper.find('.module-error button').trigger('click')
    expect(generate).toHaveBeenCalledWith(['summary'], true)
    wrapper.unmount()
  })

  it('does not expose description fallback for a temporary platform error', () => {
    const wrapper = mountWorkspace({ descriptionAvailable: true, backgroundTask: { status: 'failed', error: '平台字幕暂时不可用' } })
    expect(wrapper.find('.description-fallback').exists()).toBe(false)
    wrapper.unmount()
  })

  it('allows description summary only as a distinct manual fallback', async () => {
    const generate = vi.fn()
    const wrapper = mountWorkspace({ descriptionAvailable: true, backgroundTask: { status: 'failed', error: '没有平台字幕，语音转录不可用', result: { subtitle_unavailable: true } }, onGenerateTargets: generate, descriptionSummary: { summary: '简介内容' } })
    expect(generate).not.toHaveBeenCalled()
    await wrapper.find('.description-fallback button').trigger('click')
    expect(generate).toHaveBeenCalledWith(['summary'], false, 'description')
    expect(wrapper.find('.description-result').text()).toContain('未分析视频全文')
    wrapper.unmount()
  })
})

describe('Subtitle downloads', () => {
  it('offers TXT for plain text without inventing timestamps', async () => {
    const wrapper = mount(SubtitlePanel, { props: { text: '没有时间信息的原始字幕', info: { source: 'whisper', segments: [] } } })
    await wrapper.get('.toggle-button').trigger('click')
    expect(wrapper.text()).toContain('下载 TXT')
    expect(wrapper.text()).not.toContain('下载 SRT')
    expect(wrapper.text()).not.toContain('下载 VTT')
    wrapper.unmount()
  })

  it('offers timed formats only when every segment has real start and end times', async () => {
    const wrapper = mount(SubtitlePanel, { props: { text: '完整字幕', info: { segments: [{ start: 1.25, end: 4.2, text: '完整字幕' }] } } })
    await wrapper.get('.toggle-button').trigger('click')
    expect(wrapper.text()).toContain('下载 SRT')
    expect(wrapper.text()).toContain('下载 VTT')
    wrapper.unmount()
  })
})
