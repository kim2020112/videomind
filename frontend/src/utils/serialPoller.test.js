import { afterEach, describe, expect, it, vi } from 'vitest'
import { createSerialPoller } from './serialPoller.js'

afterEach(() => vi.useRealTimers())

describe('serial polling', () => {
  it('waits for a slow callback before scheduling another request', async () => {
    vi.useFakeTimers()
    let resolve
    const run = vi.fn(() => new Promise(done => { resolve = done }))
    const poller = createSerialPoller()
    poller.start(run)
    await vi.advanceTimersByTimeAsync(12000)
    expect(run).toHaveBeenCalledTimes(1)
    resolve(true)
    await vi.advanceTimersByTimeAsync(3000)
    expect(run).toHaveBeenCalledTimes(2)
    poller.stop()
    resolve(true)
    await vi.advanceTimersByTimeAsync(30000)
    expect(run).toHaveBeenCalledTimes(2)
  })

  it('backs off failed requests and resets after success', async () => {
    vi.useFakeTimers()
    const run = vi.fn().mockResolvedValueOnce(null).mockResolvedValue(true)
    const poller = createSerialPoller()
    poller.start(run)
    await vi.advanceTimersByTimeAsync(3000)
    await vi.advanceTimersByTimeAsync(5999)
    expect(run).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(3001)
    expect(run).toHaveBeenCalledTimes(3)
    poller.stop()
  })

  it('an old terminal response cannot stop a newly started poll', async () => {
    vi.useFakeTimers()
    let finishOld
    const poller = createSerialPoller()
    poller.start(() => new Promise(resolve => { finishOld = resolve }))
    await vi.advanceTimersByTimeAsync(3000)
    const next = vi.fn().mockResolvedValue(true)
    poller.start(next)
    finishOld(false)
    await vi.advanceTimersByTimeAsync(6000)
    expect(next).toHaveBeenCalledTimes(2)
    poller.stop()
  })
})
