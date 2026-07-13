import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import HeroSection from './HeroSection.vue'

function mountHero(props = {}) {
  return mount(HeroSection, {
    props: {
      url: 'https://example.com/video',
      loading: false,
      requiresLogin: false,
      serviceChecking: false,
      compact: false,
      ...props,
    },
  })
}

describe('HeroSection', () => {
  it('requests login before parsing when guest access is unavailable', async () => {
    const wrapper = mountHero({ requiresLogin: true })

    expect(wrapper.get('.hero-parse-button').text()).toBe('登录后开始')
    await wrapper.get('.hero-parse-button').trigger('click')

    expect(wrapper.emitted('request-login')).toHaveLength(1)
    expect(wrapper.emitted('parse')).toBeUndefined()
  })

  it('emits parse when the current identity can start', async () => {
    const wrapper = mountHero()

    expect(wrapper.get('.hero-parse-button').text()).toBe('开始学习')
    await wrapper.get('.hero-parse-button').trigger('click')

    expect(wrapper.emitted('parse')).toHaveLength(1)
  })

  it('provides an explicit URL label and compact workspace mode', () => {
    const wrapper = mountHero({ compact: true })

    expect(wrapper.get('label[for="video-url-input"]').text()).toContain('视频链接')
    expect(wrapper.get('#video-url-input').attributes('type')).toBe('url')
    expect(wrapper.classes()).toContain('hero-section--compact')
  })
})
