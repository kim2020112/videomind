import { describe, it, expect, vi, afterEach } from 'vitest'
import { effectScope } from 'vue'
import { useLearning } from './useLearning.js'
vi.mock('./useAuth.js', () => ({ useAuth: () => ({ getAuthHeaders: () => ({}), refreshUsage: vi.fn() }) }))
const snapshot = (summary = '已有摘要') => ({ subtitle: { text: '字幕原文', source: 'native' }, artifacts: { result: { summary } }, modules: { summary: { status: 'done' } }, coverage: 'partial', task: null })
let scope
function setup() { scope = effectScope(); return scope.run(() => useLearning()) }
afterEach(() => { scope?.stop(); vi.unstubAllGlobals() })
describe('durable learning workspace', () => {
  it('loads saved content without starting generation', async () => {
    const fetch = vi.fn().mockImplementation((url) => Promise.resolve(Response.json(url.endsWith('/visit') ? { recorded: true } : snapshot())))
    vi.stubGlobal('fetch', fetch)
    const state = setup()
    await state.loadWorkspace('https://example.com/video')
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(fetch.mock.calls[0][0]).toContain('/api/workspace?')
    expect(fetch.mock.calls[1][0]).toBe('/api/workspace/visit')
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ url: 'https://example.com/video' })
    expect(state.summaryResult.value.summary).toBe('已有摘要')
    expect(state.workspaceCoverage.value).toBe('partial')
  })
  it('ignores a late snapshot from the previous video', async () => {
    let resolveOld
    vi.stubGlobal('fetch', vi.fn().mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve })).mockResolvedValueOnce(Response.json(snapshot('新视频摘要'))))
    const state = setup()
    const old = state.loadWorkspace('https://example.com/old')
    await state.loadWorkspace('https://example.com/new')
    resolveOld(Response.json(snapshot('旧视频摘要')))
    await old
    expect(state.summaryResult.value.summary).toBe('新视频摘要')
  })
  it('restores a confirmation task without automatically starting transcription', async () => {
    const saved = snapshot()
    saved.task = { task_id: 'waiting', status: 'awaiting_confirmation', payload: { targets: ['notes'] } }
    const fetch = vi.fn().mockImplementation((url) => Promise.resolve(Response.json(url.endsWith('/visit') ? { recorded: true } : saved)))
    vi.stubGlobal('fetch', fetch)
    const state = setup()
    await state.loadWorkspace('https://example.com/wait')
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(state.backgroundTask.value.status).toBe('awaiting_confirmation')
    expect(state.isSummarizing.value).toBe(false)
  })
  it('retains cached content if recording the visit fails', async () => {
    vi.stubGlobal('fetch', vi.fn(url => url.endsWith('/visit') ? Promise.reject(new Error('offline')) : Promise.resolve(Response.json(snapshot()))))
    const state = setup()
    await state.loadWorkspace('https://example.com/video')
    expect(state.summaryResult.value.summary).toBe('已有摘要')
    expect(state.visitError.value).toContain('浏览记录暂未保存')
    expect(state.summarizeError.value).toBe('')
  })
  it('does not record an empty workspace', async () => {
    const fetch = vi.fn(() => Promise.resolve(Response.json({ subtitle: null, artifacts: {}, modules: {}, coverage: 'empty' })))
    vi.stubGlobal('fetch', fetch)
    await setup().loadWorkspace('https://example.com/empty')
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('clears subtitles using the returned snapshot while retaining AI materials', async () => {
    const cleared = { ...snapshot(), subtitle: null, subtitle_cleared: true }
    const fetch = vi.fn((url, options) => Promise.resolve(Response.json(options?.method === 'DELETE' ? cleared : url.endsWith('/visit') ? { recorded: true } : snapshot())))
    vi.stubGlobal('fetch', fetch)
    const state = setup()
    await state.loadWorkspace('https://example.com/video')
    await state.clearSubtitle()
    const call = fetch.mock.calls.find(([, options]) => options.method === 'DELETE')
    expect(call[0]).toBe('/api/workspace/subtitle')
    expect(JSON.parse(call[1].body)).toEqual({ url: 'https://example.com/video' })
    expect(state.subtitleText.value).toBe('')
    expect(state.subtitleCleared.value).toBe(true)
    expect(state.summaryResult.value.summary).toBe('已有摘要')
    expect(state.submitting.value).toBe(false)
  })
  it('retains subtitles and reports an error if clearing is rejected', async () => {
    vi.stubGlobal('fetch', vi.fn((url, options) => Promise.resolve(options?.method === 'DELETE' ? Response.json({ detail: '当前视频任务尚未结束' }, { status: 409 }) : Response.json(url.endsWith('/visit') ? { recorded: true } : snapshot()))))
    const state = setup()
    await state.loadWorkspace('https://example.com/video')
    await state.clearSubtitle()
    expect(state.subtitleText.value).toBe('字幕原文')
    expect(state.subtitleCleared.value).toBe(false)
    expect(state.subtitleError.value).toContain('任务尚未结束')
  })

})

it('rejects frames from an old subscription after switching videos', async () => {
  let oldStream
  const old = { ...snapshot(), task: { task_id: 'old', status: 'generating', payload: { targets: ['summary'] } } }
  vi.stubGlobal('fetch', vi.fn(url => {
    if (url.includes('/events?')) return Promise.resolve(new Response(new ReadableStream({ start(controller) { oldStream = controller } })))
    if (url.endsWith('/visit')) return Promise.resolve(Response.json({ recorded: true }))
    return Promise.resolve(Response.json(url.includes('old') ? old : snapshot('新视频摘要')))
  }))
  const state = setup()
  await state.loadWorkspace('https://example.com/old')
  await state.loadWorkspace('https://example.com/new')
  oldStream.enqueue(new TextEncoder().encode('id: 1\ndata: {"type":"artifact_saved","data":{"target":"summary","content":{"summary":"旧任务污染"}}}\n\n'))
  await new Promise(resolve => setTimeout(resolve, 10))
  expect(state.summaryResult.value.summary).toBe('新视频摘要')
})

it('stops reconnecting when task authorization expires', async () => {
  const saved = { ...snapshot(), task: { task_id: 'task', status: 'generating', payload: { targets: ['summary'] } } }
  const fetch = vi.fn(url => Promise.resolve(url.includes('/events?')
    ? Response.json({ detail: '请重新登录' }, { status: 401 })
    : Response.json(url.endsWith('/visit') ? { recorded: true } : saved)))
  vi.stubGlobal('fetch', fetch)
  const state = setup()
  await state.loadWorkspace('https://example.com/video')
  await new Promise(resolve => setTimeout(resolve, 10))
  expect(state.summarizeError.value).toBe('请重新登录')
  expect(fetch.mock.calls.filter(([url]) => url.includes('/events?'))).toHaveLength(1)
})
