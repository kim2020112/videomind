import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createRouter } from 'vue-router'
import BloggersPage from './BloggersPage.vue'
import { routes } from '../router.js'

vi.mock('../composables/useAuth.js', () => ({
  useAuth: () => ({
    getAuthHeaders: () => ({ Authorization: 'Bearer t' }),
  }),
}))

function makeRouter() {
  return createRouter({ history: createMemoryHistory(), routes })
}

function okJson(data) {
  return { ok: true, json: () => Promise.resolve(data) }
}

function blogger(overrides = {}) {
  return {
    id: 7, uid: '475210', name: '测试UP', alias: '', avatar: '',
    follower_count: 12, catalog_count: 34, learned_count: 5,
    sync_status: 'complete', created_at: '2026-01-01',
    ...overrides,
  }
}

async function mountPage(fetchMock) {
  vi.stubGlobal('fetch', fetchMock)
  const router = makeRouter()
  await router.push('/bloggers')
  await router.isReady()
  const wrapper = mount(BloggersPage, { global: { plugins: [router], stubs: { teleport: true } } })
  await flushPromises()
  return wrapper
}

describe('BloggersPage', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders bloggers with learned chips and emits open-blogger', async () => {
    const wrapper = await mountPage(vi.fn().mockResolvedValue(okJson({ bloggers: [blogger()] })))
    expect(wrapper.text()).toContain('测试UP')
    expect(wrapper.text()).toContain('34 投稿')
    expect(wrapper.text()).toContain('已整理 5')

    await wrapper.find('.blogger-card').trigger('click')
    expect(wrapper.emitted('open-blogger')[0][0].id).toBe(7)
    wrapper.unmount()
  })

  it('previews before subscribing and posts after confirm', async () => {
    const fetchMock = vi.fn().mockImplementation((url, options) => {
      if (options?.method === 'POST' && url === '/api/bloggers/preview') {
        return Promise.resolve(okJson({
          profile: { uid: '475210', name: '何同学', avatar: '', follower_count: 100 },
          already_subscribed: false,
          sub: null,
        }))
      }
      if (options?.method === 'POST' && url === '/api/bloggers') {
        return Promise.resolve(okJson({ sub: { id: 1 }, sync: { id: 2 }, created: true, already_subscribed: false }))
      }
      return Promise.resolve(okJson({ bloggers: [] }))
    })
    const wrapper = await mountPage(fetchMock)

    await wrapper.find('.bloggers-header .btn-primary').trigger('click')
    await wrapper.find('#blogger-input').setValue('475210')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    // 第一步：预览，未直接订阅
    const previewCall = fetchMock.mock.calls.find(call => call[0] === '/api/bloggers/preview')
    expect(JSON.parse(previewCall[1].body)).toEqual({ input: '475210' })
    expect(wrapper.find('.preview-card').exists()).toBe(true)
    expect(wrapper.text()).toContain('何同学')
    expect(fetchMock.mock.calls.some(call => call[0] === '/api/bloggers' && call[1]?.method === 'POST')).toBe(false)

    // 第二步：确认订阅
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const addCall = fetchMock.mock.calls.find(call => call[0] === '/api/bloggers' && call[1]?.method === 'POST')
    expect(JSON.parse(addCall[1].body)).toEqual({ input: '475210' })
    wrapper.unmount()
  })

  it('shows already-subscribed state with go/refresh actions instead of re-adding', async () => {
    const fetchMock = vi.fn().mockImplementation((url, options) => {
      if (url === '/api/bloggers/preview') {
        return Promise.resolve(okJson({
          profile: { uid: '100', name: '已关注UP', avatar: '', follower_count: 9 },
          already_subscribed: true,
          sub: { id: 3, uid: '100', name: '已关注UP' },
        }))
      }
      return Promise.resolve(okJson({ bloggers: [blogger({ id: 3, uid: '100', name: '已关注UP' })] }))
    })
    const wrapper = await mountPage(fetchMock)

    await wrapper.find('.bloggers-header .btn-primary').trigger('click')
    await wrapper.find('#blogger-input').setValue('100')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('已订阅')
    const buttons = wrapper.findAll('.add-actions button').map(b => b.text())
    expect(buttons).toContain('刷新目录')
    expect(buttons).toContain('去详情页')
    // 不再静默 POST /api/bloggers
    expect(fetchMock.mock.calls.some(call => call[0] === '/api/bloggers' && call[1]?.method === 'POST')).toBe(false)
    wrapper.unmount()
  })

  it('saves alias via inline edit', async () => {
    const fetchMock = vi.fn().mockImplementation((url, options) => {
      if (options?.method === 'PATCH') return Promise.resolve(okJson({ sub: {} }))
      return Promise.resolve(okJson({ bloggers: [blogger()] }))
    })
    const wrapper = await mountPage(fetchMock)

    await wrapper.find('.blogger-name-row .btn-icon-only').trigger('click')
    const input = wrapper.find('.alias-input')
    await input.setValue('我的备注')
    await input.trigger('keyup.enter')
    await flushPromises()

    const patch = fetchMock.mock.calls.find(call => call[1]?.method === 'PATCH')
    expect(patch[0]).toBe('/api/bloggers/7')
    expect(JSON.parse(patch[1].body)).toEqual({ alias: '我的备注' })
    wrapper.unmount()
  })

  it('filters by search query client-side', async () => {
    const wrapper = await mountPage(vi.fn().mockResolvedValue(okJson({
      bloggers: [blogger({ id: 1, name: '何同学' }), blogger({ id: 2, uid: '200', name: '影视飓风' })],
    })))
    await wrapper.find('.search-input').setValue('何同学')
    await flushPromises()
    const names = wrapper.findAll('.blogger-name').map(el => el.text())
    expect(names).toEqual(['何同学'])
    wrapper.unmount()
  })

  it('opens deletion preview dialog with preserved note', async () => {
    const fetchMock = vi.fn().mockImplementation((url, options) => {
      if (url.includes('deletion-preview')) {
        return Promise.resolve(okJson({
          sub: blogger(),
          will_remove: { subscription: 1, videos: 34, pages: 40, batches: 2, syncs: 5 },
          cascade: true,
          remaining_subscribers: 0,
          blocked_by_active: { sync: false, batch: false },
          preserved: { ai_cache: true, subtitles: true, user_history: true, note: '摘要/笔记/思维导图/问答、字幕、学习历史全部保留；重新订阅后批量生成自动复用缓存，不重复解析' },
        }))
      }
      return Promise.resolve(okJson({ bloggers: [blogger()] }))
    })
    const wrapper = await mountPage(fetchMock)

    await wrapper.find('.btn-ghost--danger').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('将清理')
    expect(wrapper.text()).toContain('投稿目录 × 34')
    expect(wrapper.text()).toContain('全部保留')
    wrapper.unmount()
  })

  it('surfaces API errors as a toast', async () => {
    const wrapper = await mountPage(vi.fn().mockResolvedValue({
      ok: false, json: () => Promise.resolve({ detail: '需要登录或有效游客身份' }),
    }))
    await wrapper.find('.bloggers-header .btn-primary').trigger('click')
    await wrapper.find('#blogger-input').setValue('not-a-uid')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('.app-toast').exists()).toBe(true)
    expect(wrapper.text()).toContain('需要登录或有效游客身份')
    wrapper.unmount()
  })
})
