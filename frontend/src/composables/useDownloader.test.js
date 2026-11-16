import { afterEach, describe, expect, it, vi } from 'vitest'
import { useDownloader } from './useDownloader.js'
vi.mock('./useAuth.js', () => ({ useAuth: () => ({ getAuthHeaders: () => ({}), getAuthQueryParams: () => new URLSearchParams() }) }))
vi.mock('vue', async original => ({ ...await original(), onUnmounted: vi.fn() }))
afterEach(() => vi.unstubAllGlobals())

describe('workbench video parsing', () => {
  it.each([502, 503])('explains an empty HTTP %s without exposing JSON syntax errors', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status })))
    await expect(useDownloader().parseVideo('https://example.com/video')).rejects.toThrow('服务暂时不可用')
  })
  it('preserves a structured upstream protection message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ detail: '字幕暂时受限' }, { status: 429 })))
    await expect(useDownloader().parseVideo('https://example.com/video')).rejects.toThrow('字幕暂时受限')
  })
  it('opens learning metadata without requiring video download formats', async () => {
    const url = 'https://www.bilibili.com/video/BV1test'
    const fetch = vi.fn().mockResolvedValue(Response.json({ title: 'Synced', webpage_url: url, formats: [] }))
    vi.stubGlobal('fetch', fetch)
    const state = useDownloader()
    await state.parseVideo(url)
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ url, metadata_only: true })
    expect(state.videoInfo.value.title).toBe('Synced')
    expect(state.isParsing.value).toBe(false)
  })
  it('handles an empty successful response with a useful message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('')))
    await expect(useDownloader().parseVideo('https://example.com')).rejects.toThrow('视频信息不完整')
  })
})

it('ignores a previous video response arriving after the new video', async () => {
  const pending = []
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => pending.push(resolve))))
  const state = useDownloader()
  const first = state.parseVideo('https://example.com/A')
  const second = state.parseVideo('https://example.com/B')
  pending[1](Response.json({ title: 'B', webpage_url: 'https://example.com/B' }))
  await second
  pending[0](Response.json({ title: 'A', webpage_url: 'https://example.com/A' }))
  expect(await first).toBe(false)
  expect(state.videoInfo.value.title).toBe('B')
})

it('reset invalidates an outstanding parse even if cancellation is ignored', async () => {
  let finish
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { finish = resolve })))
  const state = useDownloader()
  const pending = state.parseVideo('https://example.com/A')
  state.reset()
  finish(Response.json({ title: 'A', webpage_url: 'https://example.com/A' }))
  expect(await pending).toBe(false)
  expect(state.videoInfo.value).toBeNull()
})

it('loads download formats on demand without clearing the current video', async () => {
  const url = 'https://www.bilibili.com/video/BVtest'
  const fetch = vi.fn()
    .mockResolvedValueOnce(Response.json({ title: 'Video', webpage_url: url, formats: [] }))
    .mockResolvedValueOnce(Response.json({ title: 'Video', webpage_url: url, formats: [{ format_id: '1080', is_best: true }] }))
  vi.stubGlobal('fetch', fetch)
  const state = useDownloader()
  await state.parseVideo(url)
  const a = state.loadDownloadFormats(url)
  const b = state.loadDownloadFormats(url)
  await Promise.all([a, b])
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(JSON.parse(fetch.mock.calls[1][1].body).metadata_only).toBe(false)
  expect(state.videoInfo.value.title).toBe('Video')
  expect(state.selectedFormat.value).toBe('1080')
})
