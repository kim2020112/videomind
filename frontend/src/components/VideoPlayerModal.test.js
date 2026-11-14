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

  it('waits for media metadata before seeking to a clicked summary timestamp', async () => {
    const wrapper = mount(VideoPlayerModal, {
      props: { visible: true, streamUrl: 'https://cdn.example/video.m4s' },
      global: { stubs: { BaseDialog: { template: '<div><slot /></div>' } } },
    })
    const video = wrapper.get('video').element
    Object.defineProperty(video, 'readyState', { configurable: true, value: 0 })
    vi.spyOn(video, 'play').mockResolvedValue()

    wrapper.vm.seekTo(42)
    expect(video.currentTime).not.toBe(42)

    Object.defineProperty(video, 'readyState', { configurable: true, value: 1 })
    await wrapper.get('video').trigger('loadedmetadata')
    expect(video.currentTime).toBe(42)
  })

  it('refreshes a missing stream URL before showing the player', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: async () => ({ stream_url: 'https://cdn.example/fresh.m4s' }),
    }))
    const wrapper = mount(VideoPlayerModal, {
      props: { visible: true, streamUrl: '', videoUrl: 'https://www.bilibili.com/video/BV1demo' },
      global: { stubs: { BaseDialog: { template: '<div><slot /></div>' } } },
    })

    await vi.waitFor(() => expect(wrapper.get('video').attributes('src')).toContain(encodeURIComponent('https://cdn.example/fresh.m4s')))
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/video/refresh?'), expect.any(Object))
    vi.unstubAllGlobals()
  })

  it('keeps the media element mounted while recovering an expired stream', async () => {
    let resolveRefresh
    vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { resolveRefresh = resolve })))
    const wrapper = mount(VideoPlayerModal, {
      props: { visible: true, streamUrl: 'https://cdn.example/expired.m4s', videoUrl: 'https://www.bilibili.com/video/BV1demo' },
      global: { stubs: { BaseDialog: { template: '<div><slot /></div>' } } },
    })
    const video = wrapper.get('video').element
    await wrapper.get('video').trigger('error')
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(wrapper.get('video').element).toBe(video)

    resolveRefresh({ json: async () => ({ stream_url: 'https://cdn.example/fresh.m4s' }) })
    await vi.waitFor(() => expect(wrapper.get('video').attributes('src')).toContain('fresh.m4s'))
    expect(wrapper.get('video').element).toBe(video)
    vi.unstubAllGlobals()
  })
})
