import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createRouter } from 'vue-router'
import BloggerDetailPage from './BloggerDetailPage.vue'
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
    props: { activeTasks: [] },
    global: { plugins: [router], stubs: { teleport: true } },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('BloggerDetailPage', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  it('appends on load more without replacing existing items', async () => {
    const fetchMock = vi.fn().mockImplementation((url) => {
      if (url.includes('/videos?') || url.includes('/videos')) {
        const offset = Number((url.match(/offset=(\d+)/) || [])[1] || 0)
        const items = offset === 0
          ? [video(1, 'BV1aaa', '视频一'), video(2, 'BV1bbb', '视频二')]
          : [video(3, 'BV1ccc', '视频三')]
        return Promise.resolve(okJson({ total: 3, learned_total: 1, items }))
      }
      if (url.includes('/batches')) return Promise.resolve(okJson({ batches: [] }))
      return Promise.resolve(okJson({ bloggers: [{ id: 7, uid: '100', name: 'UP主', alias: '', follower_count: 5, catalog_count: 3, sync_status: 'complete' }] }))
    })
    const { wrapper } = await mountPage(fetchMock)

    expect(wrapper.findAll('.video-card')).toHaveLength(2)
    expect(wrapper.text()).toContain('已学 1 / 共 3')

    await wrapper.find('.list-footer .btn-ghost').trigger('click')
    await flushPromises()
    const titles = wrapper.findAll('.video-title-text').map(el => el.text())
    expect(titles).toEqual(['视频一', '视频二', '视频三'])  // 追加而非替换
    expect(wrapper.find('.list-footer .btn-ghost').exists()).toBe(false)  // hasMore=false
    wrapper.unmount()
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
