import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createRouter } from 'vue-router'
import BloggerDetailPage from './BloggerDetailPage.vue'
import { bloggerContextKey, saveBloggerContext, clearBloggerPages } from '../utils/bloggerNavigation.js'
import { routes } from '../router.js'

vi.mock('../composables/useAuth.js', () => ({
  useAuth: () => ({
    getAuthHeaders: () => ({ Authorization: 'Bearer t' }),
  }),
}))

function makeRouter(initial = '/bloggers/7') {
  const router = createRouter({ history: createMemoryHistory(), routes })
  return router.push(initial).then(() => router)
}

function okJson(data) {
  return { ok: true, json: () => Promise.resolve(data) }
}

function video(id, bvid, title, overrides = {}) {
  return {
    id, bvid, title, cover: '', duration: 60, page_count: 1,
    published_at: 1700000000, url: `https://www.bilibili.com/video/${bvid}`,
    is_learned: false, learned_parts: [],
    ...overrides,
  }
}

async function mountPage(fetchMock, initialRoute = '/bloggers/7') {
  vi.stubGlobal('fetch', fetchMock)
  const router = await makeRouter(initialRoute)
  const wrapper = mount(BloggerDetailPage, {
    attachTo: document.body,
    props: { activeTasks: [] },
    global: { plugins: [router], stubs: { teleport: true } },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('BloggerDetailPage', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    sessionStorage.clear()
    localStorage.clear()
    clearBloggerPages()
    window.scrollTo = vi.fn()
    Element.prototype.scrollIntoView = vi.fn()
  })

  it('restores a single page and includes filters and video position in the workspace origin', async () => {
    const fetchMock = vi.fn().mockImplementation((url) => {
      if (url.includes('/videos')) {
        const offset = Number(new URL(url, 'http://localhost').searchParams.get('offset'))
        return Promise.resolve(okJson({ total: 45, learned_total: 0,
          items: Array.from({ length: 20 }, (_, index) => {
            const id = offset + index + 1
            return video(id, `BV${id}`, `视频${id}`)
          }),
        }))
      }
      if (url.includes('/batches')) return Promise.resolve(okJson({ batches: [] }))
      return Promise.resolve(okJson({ bloggers: [{ id: 7, name: 'UP主', sync_status: 'complete' }] }))
    })
    const { wrapper, router } = await mountPage(fetchMock, '/bloggers/7?q=相机&learned=unlearned&page=2#video-25')
    expect(wrapper.findAll('.video-card')).toHaveLength(20)
    expect(fetchMock.mock.calls.filter(([url]) => url.includes('/videos')).map(([url]) => new URL(url, 'http://localhost').searchParams.get('offset'))).toEqual(['20'])
    await wrapper.find('#video-25 .video-actions button').trigger('click')
    await flushPromises()
    const payload = wrapper.emitted('open-workspace')[0][0]
    const target = new URL(payload.returnTo, 'http://localhost')
    expect(target.pathname).toBe('/bloggers/7')
    expect(target.searchParams.get('q')).toBe('相机')
    expect(target.searchParams.get('learned')).toBe('unlearned')
    expect(target.searchParams.get('page')).toBe('2')
    expect(target.hash).toBe('#video-25')
    expect(router.currentRoute.value.hash).toBe('#video-25')
    wrapper.unmount()
  })

  it('retains the parent video position when opening a multipart video', async () => {
    const fetchMock = vi.fn().mockImplementation((url) => {
      if (url.includes('/pages')) return Promise.resolve(okJson({ pages: [{ cid: 55, page: 2, part_title: '第二集', url: 'https://www.bilibili.com/video/BV1aaa?p=2' }] }))
      if (url.includes('/videos')) return Promise.resolve(okJson({ total: 1, items: [video(9, 'BV1aaa', '课程', { page_count: 2 })] }))
      if (url.includes('/batches')) return Promise.resolve(okJson({ batches: [] }))
      return Promise.resolve(okJson({ bloggers: [{ id: 7, name: 'UP主', sync_status: 'complete' }] }))
    })
    const { wrapper } = await mountPage(fetchMock)
    await wrapper.find('.video-main').trigger('click')
    await flushPromises()
    await wrapper.find('.part-row button').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('open-workspace')[0][0]).toMatchObject({
      url: 'https://www.bilibili.com/video/BV1aaa?p=2', returnTo: '/bloggers/7?pageSize=20#video-9',
    })
    wrapper.unmount()
  })

  it('restores the saved anchor offset and expanded parts after a workspace reload', async () => {
    const key = bloggerContextKey('guest:local', '7', { q: '', learned: 'all' })
    saveBloggerContext(key, { videoId: 9, index: 0, loadedCount: 1, expandedVideoId: 9, offset: 240, neighbors: [9] })
    const rect = vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ top: 700 })
    const fetchMock = vi.fn((url) => {
      if (url.includes('/pages')) return Promise.resolve(okJson({ pages: [{ cid: 4, page: 2, part_title: '第二集' }] }))
      if (url.includes('/videos')) return Promise.resolve(okJson({ total: 1, anchor_index: 0, items: [video(9, 'BV1aaa', '课程', { page_count: 2 })] }))
      if (url.includes('/batches')) return Promise.resolve(okJson({ batches: [] }))
      return Promise.resolve(okJson({ bloggers: [] }))
    })
    const { wrapper } = await mountPage(fetchMock, '/bloggers/7#video-9')
    expect(wrapper.find('.parts-panel').exists()).toBe(true)
    expect(wrapper.find('#video-9').classes()).toContain('video-card--restored')
    expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 460, behavior: 'instant' })
    wrapper.unmount()
    rect.mockRestore()
  })

  it('keeps filters when the previous video no longer matches, then reveals it on request', async () => {
    const fetchMock = vi.fn((url) => {
      if (url.includes('/videos')) {
        const filtered = url.includes('learned=unlearned')
        return Promise.resolve(okJson({ total: 1, anchor_index: filtered ? null : 0,
          items: [video(filtered ? 10 : 9, 'BV1aaa', '课程')] }))
      }
      if (url.includes('/batches')) return Promise.resolve(okJson({ batches: [] }))
      return Promise.resolve(okJson({ bloggers: [] }))
    })
    const { wrapper, router } = await mountPage(fetchMock, '/bloggers/7?learned=unlearned#video-9')
    expect(wrapper.find('.return-notice').text()).toContain('不在当前筛选中')
    expect(router.currentRoute.value.query.learned).toBe('unlearned')
    await wrapper.find('.return-notice button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.learned).toBeUndefined()
    expect(wrapper.find('#video-9').exists()).toBe(true)
    expect(wrapper.find('.return-notice').exists()).toBe(false)
    wrapper.unmount()
  })

  it('combines subtitle and organized filters and preserves both in the origin', async () => {
    const fetchMock = vi.fn((url) => {
      if (url.includes('/videos')) return Promise.resolve(okJson({ total: 1, items: [video(9, 'BV1aaa', '课程')] }))
      if (url.includes('/batches')) return Promise.resolve(okJson({ batches: [] }))
      return Promise.resolve(okJson({ bloggers: [] }))
    })
    const { wrapper, router } = await mountPage(fetchMock)
    await wrapper.findAll('.filter-chip')[2].trigger('click')
    await flushPromises()
    await wrapper.find('.subtitle-filter input').setValue(true)
    await flushPromises()
    expect(router.currentRoute.value.query).toMatchObject({ learned: 'unlearned', has_subtitle: '1' })
    expect(fetchMock.mock.calls.some(([url]) => url.includes('learned=unlearned') && url.includes('has_subtitle=1'))).toBe(true)
    await wrapper.find('.video-actions button').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('open-workspace')[0][0].returnTo).toContain('has_subtitle=1')
    wrapper.unmount()
  })

  it('replaces the page, changes page size and clears page selection', async () => {
    const fetchMock = vi.fn((url) => {
      if (url.includes('/videos')) {
        const params = new URL(url, 'http://localhost').searchParams
        const offset = Number(params.get('offset'))
        const limit = Number(params.get('limit'))
        return Promise.resolve(okJson({ total: 45, offset, limit, items: Array.from({ length: Math.min(limit, 45 - offset) }, (_, i) => video(offset + i + 1, `BV${i}`, `视频${offset + i + 1}`)) }))
      }
      return Promise.resolve(okJson({ bloggers: [], batches: [] }))
    })
    const { wrapper, router } = await mountPage(fetchMock)
    expect(wrapper.findAll('.video-card')).toHaveLength(20)
    await wrapper.find('.list-top button[aria-label="下一页"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('#video-1').exists()).toBe(false)
    expect(wrapper.find('#video-21').exists()).toBe(true)
    expect(router.currentRoute.value.query.page).toBe('2')
    await wrapper.find('.list-top select').setValue('10')
    await flushPromises()
    expect(wrapper.findAll('.video-card')).toHaveLength(10)
    expect(router.currentRoute.value.query).toMatchObject({ page: '3', pageSize: '10' })
    expect(wrapper.find('#video-21').exists()).toBe(true)
    await wrapper.find('.list-top input').setValue('5')
    await wrapper.find('.list-top form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('#video-41').exists()).toBe(true)
    wrapper.unmount()
  })

  it('paints a warm page before delayed list, metadata and batch requests finish', async () => {
    const fetchMock = vi.fn((url) => Promise.resolve(okJson(url.includes('/videos')
      ? { total: 1, offset: 0, items: [video(9, 'BV9', '缓存课程')] }
      : { bloggers: [], batches: [] })))
    const first = await mountPage(fetchMock)
    await first.wrapper.find('.video-actions button').trigger('click')
    await flushPromises()
    first.wrapper.unmount()
    const delayed = vi.fn(() => new Promise(() => {}))
    const second = await mountPage(delayed, '/bloggers/7?pageSize=20#video-9')
    expect(second.wrapper.find('#video-9').exists()).toBe(true)
    expect(second.wrapper.find('.detail-empty').exists()).toBe(false)
    second.wrapper.unmount()
  })

  it('writes learned filter to query and refetches', async () => {
    const calls = []
    const fetchMock = vi.fn().mockImplementation((url) => {
      calls.push(url)
      if (url.includes('/videos')) {
        return Promise.resolve(okJson({ total: 0, learned_total: 0, items: [] }))
      }
      if (url.includes('/batches')) return Promise.resolve(okJson({ batches: [] }))
      return Promise.resolve(okJson({ bloggers: [{ id: 7, uid: '100', name: 'UP主', sync_status: 'complete' }] }))
    })
    const { wrapper, router } = await mountPage(fetchMock)

    await wrapper.findAll('.filter-chip')[1].trigger('click')  // 已学
    await flushPromises()
    expect(router.currentRoute.value.query.learned).toBe('learned')
    expect(calls.some(url => url.includes('learned=learned'))).toBe(true)
    wrapper.unmount()
  })

  it('restores filters from route query', async () => {
    const calls = []
    const fetchMock = vi.fn().mockImplementation((url) => {
      calls.push(url)
      if (url.includes('/videos')) {
        return Promise.resolve(okJson({ total: 0, learned_total: 0, items: [] }))
      }
      if (url.includes('/batches')) return Promise.resolve(okJson({ batches: [] }))
      return Promise.resolve(okJson({ bloggers: [{ id: 7, uid: '100', name: 'UP主', sync_status: 'complete' }] }))
    })
    const { wrapper } = await mountPage(fetchMock, '/bloggers/7?q=相机&learned=unlearned')

    expect(calls.some(url => url.includes('q=') && url.includes('learned=unlearned'))).toBe(true)
    wrapper.unmount()
  })

  it('shows sync bar with progress and cancel while active', async () => {
    const fetchMock = vi.fn().mockImplementation((url) => {
      if (url.includes('/videos')) {
        return Promise.resolve(okJson({ total: 0, learned_total: 0, items: [] }))
      }
      if (url.includes('/batches')) return Promise.resolve(okJson({ batches: [] }))
      return Promise.resolve(okJson({
        bloggers: [{
          id: 7, uid: '100', name: 'UP主', sync_status: 'running', sync_mode: 'deep',
          sync_page: 3, sync_found: 90, sync_added: 5, sync_expected: 200,
        }],
      }))
    })
    const { wrapper } = await mountPage(fetchMock)

    expect(wrapper.find('.sync-bar').exists()).toBe(true)
    expect(wrapper.text()).toContain('深度同步中')
    expect(wrapper.text()).toContain('第 3 页')
    expect(wrapper.find('.sync-bar-actions').text()).toContain('取消同步')
    wrapper.unmount()
  })

  it('edits alias from header', async () => {
    const fetchMock = vi.fn().mockImplementation((url, options) => {
      if (options?.method === 'PATCH') return Promise.resolve(okJson({ sub: {} }))
      if (url.includes('/videos')) return Promise.resolve(okJson({ total: 0, learned_total: 0, items: [] }))
      if (url.includes('/batches')) return Promise.resolve(okJson({ batches: [] }))
      return Promise.resolve(okJson({ bloggers: [{ id: 7, uid: '100', name: 'UP主', alias: '', sync_status: 'complete' }] }))
    })
    const { wrapper } = await mountPage(fetchMock)

    await wrapper.find('.detail-title-row .btn-icon-only').trigger('click')
    await wrapper.find('.alias-input').setValue('新备注')
    await wrapper.find('.alias-input').trigger('keyup.enter')
    await flushPromises()

    const patch = fetchMock.mock.calls.find(call => call[1]?.method === 'PATCH')
    expect(patch[0]).toBe('/api/bloggers/7')
    expect(JSON.parse(patch[1].body)).toEqual({ alias: '新备注' })
    wrapper.unmount()
  })
})
