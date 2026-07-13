import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import VideoContextPanel from './VideoContextPanel.vue'

describe('VideoContextPanel mobile summary', () => {
  it('starts collapsed and reveals secondary video details on demand', async () => {
    const wrapper = mount(VideoContextPanel, {
      props: {
        collapsible: true,
        videoInfo: {
          title: '测试视频',
          extractor: 'bilibili',
          uploader: '作者',
          description: '详细描述',
          thumbnail: 'https://example.com/thumb.jpg',
        },
      },
    })

    expect(wrapper.get('.mobile-context-toggle').attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('.video-info').exists()).toBe(false)

    await wrapper.get('.mobile-context-toggle').trigger('click')

    expect(wrapper.get('.mobile-context-toggle').attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('.video-info').text()).toContain('作者')
  })
})
