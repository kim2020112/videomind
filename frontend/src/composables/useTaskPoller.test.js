import { afterEach, describe, expect, it, vi } from 'vitest'
import { useTaskPoller } from './useTaskPoller.js'

vi.mock('./useAuth.js', () => ({ useAuth: () => ({ getAuthHeaders: () => ({}) }) }))
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
const reply = tasks => ({ ok: true, json: async () => ({ tasks }) })

describe('task polling lifecycle', () => {
  it('coalesces concurrent manual and scheduled checks', async () => {
    vi.useFakeTimers()
    let finish
    const fetch = vi.fn(() => new Promise(resolve => { finish = resolve }))
    vi.stubGlobal('fetch', fetch)
    const state = useTaskPoller()
    state.startPolling()
    const first = state.pollOnce()
    expect(state.pollOnce()).toBe(first)
    await Promise.resolve()
    expect(fetch).toHaveBeenCalledTimes(1)
    finish(reply([]))
    await first
    state.stopPolling()
    await vi.advanceTimersByTimeAsync(60000)
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('aborts stopped requests and ignores their late responses after restart', async () => {
    vi.useFakeTimers()
    let finishOld
    const fetch = vi.fn()
      .mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
      .mockResolvedValue(reply([{ task_id: 'new' }]))
    vi.stubGlobal('fetch', fetch)
    const state = useTaskPoller()
    state.startPolling()
    const old = state.pollOnce()
    await Promise.resolve()
    state.stopPolling()
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true)
    state.startPolling()
    await state.pollOnce()
    finishOld(reply([{ task_id: 'old' }]))
    await old
    expect(state.activeTasks.value).toEqual([{ task_id: 'new' }])
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetch).toHaveBeenCalledTimes(3)
    state.stopPolling()
  })

  it('stops automatic checks when the session is no longer authorized', async () => {
    vi.useFakeTimers()
    const fetch = vi.fn().mockResolvedValue({ ok: false, status: 401 })
    vi.stubGlobal('fetch', fetch)
    const state = useTaskPoller()
    state.startPolling()
    await state.pollOnce()
    await vi.advanceTimersByTimeAsync(120000)
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(state.activeTasks.value).toEqual([])
  })
})
