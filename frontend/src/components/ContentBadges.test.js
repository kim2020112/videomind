import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ContentBadges from './ContentBadges.vue'

describe('saved content badges', () => {
  it('distinguishes subtitles, real modules and description-only summaries', async () => {
    const wrapper = mount(ContentBadges, { props: { content: { has_subtitle: true, module_count: 0 } } })
    expect(wrapper.find('.content-badge').text()).toContain('有字幕')
    expect(wrapper.text()).not.toContain('已整理 ·')
    await wrapper.setProps({ content: { module_count: 2, modules: ['summary', 'notes'], has_subtitle: true, stale_modules: ['notes'] } })
    expect(wrapper.find('.content-badge').text()).toContain('已整理 · 2/4')
    expect(wrapper.find('[role=tooltip]').text()).toContain('摘要、笔记')
    expect(wrapper.find('[role=tooltip]').text()).toContain('字幕或提示词已更新')
    await wrapper.setProps({ content: { has_description_summary: true } })
    expect(wrapper.find('.content-badge').text()).toContain('简介摘要')
    expect(wrapper.text()).not.toContain('已整理 ·')
  })
  it('aggregates multipart subtitles and organized parts separately', () => {
    const wrapper = mount(ContentBadges, { props: { totalParts: 12, subtitleParts: [1,2,3,4,5,6,7], organizedParts: [1,2,3] } })
    expect(wrapper.findAll('.content-badge')).toHaveLength(2)
    expect(wrapper.text()).toContain('有字幕 7/12P')
    expect(wrapper.text()).toContain('已整理 3/12P')
  })
  it('supports focus descriptions and Escape dismissal', async () => {
    const wrapper = mount(ContentBadges, { props: { content: { has_subtitle: true } } })
    const badge = wrapper.find('.content-badge')
    expect(badge.attributes('tabindex')).toBe('0')
    expect(badge.attributes('aria-describedby')).toBe(wrapper.find('[role=tooltip]').attributes('id'))
    await badge.trigger('keydown.esc')
    expect(wrapper.find('[role=tooltip]').classes()).toContain('dismissed')
    await badge.trigger('focus')
    expect(wrapper.find('[role=tooltip]').classes()).not.toContain('dismissed')
  })
})
