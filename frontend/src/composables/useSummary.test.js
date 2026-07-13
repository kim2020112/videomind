import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./useAuth.js', () => ({
  useAuth: () => ({
    getAuthHeaders: () => ({ 'Content-Type': 'application/json' }),
    refreshUsage: vi.fn(),
  }),
}))

function deferred() {
  let resolve
  const promise = new Promise(r => { resolve = r })
  return { promise, resolve }
}

function streamingResponse(readResult) {
  let reads = 0
  return {
    ok: true,
    body: { getReader: () => ({
      read: () => reads++ === 0 ? readResult.promise : Promise.resolve({ done: true }),
    }) },
  }
}

describe('useSummary stream lifecycle', () => {
  beforeEach(() => vi.unstubAllGlobals())

  it('aborts the active stream when summary state is reset', async () => {
    const read = deferred()
    let signal
    vi.stubGlobal('fetch', vi.fn((_url, options) => {
      signal = options.signal
      return Promise.resolve(streamingResponse(read))
    }))
    const { useSummary } = await import('./useSummary.js')
    const summary = useSummary()

    summary.summarizeVideoStream('https://example.com/one')
    await Promise.resolve()
    summary.resetSummary()

    expect(signal.aborted).toBe(true)
    expect(summary.isSummarizing.value).toBe(false)
  })

  it('does not let an older stream finish or write into a newer request', async () => {
    const firstRead = deferred()
    const secondRead = deferred()
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(streamingResponse(firstRead))
      .mockResolvedValueOnce(streamingResponse(secondRead)))
    const { useSummary } = await import('./useSummary.js')
    const summary = useSummary()

    const first = summary.summarizeVideoStream('https://example.com/one')
    await Promise.resolve()
    const second = summary.summarizeVideoStream('https://example.com/two')
    await Promise.resolve()

    firstRead.resolve({
      done: false,
      value: new TextEncoder().encode('data: {"type":"text","data":{"text":"旧结果"}}\n'),
    })
    await first

    expect(summary.streamingText.value).toBe('')
    expect(summary.isSummarizing.value).toBe(true)

    secondRead.resolve({ done: true })
    await second
    expect(summary.isSummarizing.value).toBe(false)
  })

  it('clears the previous part source before a new full summary', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamingResponse({
      promise: Promise.resolve({ done: true }),
    })))
    const { useSummary } = await import('./useSummary.js')
    const summary = useSummary()
    summary.subtitleSource.value = 'bilibili_cc'
    summary.generationStage.value = 'notes'

    await summary.summarizeVideoStream('https://example.com/two')

    expect(summary.subtitleSource.value).toBe('')
    expect(summary.generationStage.value).toBe('')
  })
})
