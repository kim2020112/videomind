import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import VideoPlayerModal from './VideoPlayerModal.vue'

vi.mock('../composables/useAuth.js', () => ({
  useAuth: () => ({
    getAuthHeaders: () => ({ Authorization: 'Bearer admin-window-session' }),
    getAuthQueryParams: () => new URLSearchParams({ session_id: 'admin-window-session' }),
    guestId: { value: '' },
    guestSig: { value: '' },
  }),
}))

describe('VideoPlayerModal window authentication', () => {
  it('adds the current window session to the media proxy URL', async () => {
    const wrapper = mount(VideoPlayerModal, {
      props: {
        visible: false,
        streamUrl: 'https://cdn.example/video.m4s',
        videoUrl: 'https://www.bilibili.com/video/BV1demo',
      },
      global: {
        stubs: {
          BaseDialog: { template: '<div><slot /></div>' },
        },
      },
    })

    await wrapper.setProps({ visible: true })

    expect(wrapper.get('video').attributes('src')).toContain('session_id=admin-window-session')
  })

  it('creates the companion audio element only for split streams', async () => {
    const wrapper = mount(VideoPlayerModal, {
      props: {
        visible: true,
        streamUrl: 'https://cdn.example/video.m4s',
        audioStreamUrl: 'https://cdn.example/audio.m4s',
        streamNeedsAudio: true,
        videoUrl: 'https://www.bilibili.com/video/BV1demo',
      },
      global: { stubs: { BaseDialog: { template: '<div><slot /></div>' } } },
    })

    await wrapper.vm.$nextTick()
    expect(wrapper.find('audio').exists()).toBe(true)
    await wrapper.setProps({ streamNeedsAudio: false })
    expect(wrapper.find('audio').exists()).toBe(false)
  })

  it('emits the selected playback rate', async () => {
    const wrapper = mount(VideoPlayerModal, {
      props: { visible: true, streamUrl: 'https://cdn.example/video.m4s' },
      global: { stubs: { BaseDialog: { template: '<div><slot /></div>' } } },
    })

    await wrapper.get('button[aria-pressed="false"]').trigger('click')
    expect(wrapper.emitted('playback-rate-change')?.[0]).toEqual([1.5])
  })
})
