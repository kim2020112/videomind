import { beforeEach, describe, expect, it, vi } from 'vitest'

async function loadComposable() {
  vi.resetModules()
  return import('./useCapabilities.js')
}

describe('useCapabilities', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  it('starts from a safe disabled state', async () => {
    const { useCapabilities } = await loadComposable()
    const { capabilities, loaded, error } = useCapabilities()

    expect(capabilities.value).toEqual({
      ai: false,
      whisper: false,
      ffmpeg: false,
      guest_access_enabled: false,
    })
    expect(loaded.value).toBe(false)
    expect(error.value).toBe('')
  })

  it('keeps features disabled and exposes a retryable error on network failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    const { useCapabilities } = await loadComposable()
    const { capabilities, loaded, error, fetchCapabilities } = useCapabilities()

    const ok = await fetchCapabilities()

    expect(ok).toBe(false)
    expect(loaded.value).toBe(true)
    expect(error.value).toBe('无法获取服务能力，请稍后重试')
    expect(capabilities.value.ai).toBe(false)
    expect(capabilities.value.guest_access_enabled).toBe(false)
  })

  it('normalizes missing capability fields to false', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ ai: true }),
    }))
    const { useCapabilities } = await loadComposable()
    const { capabilities, error, fetchCapabilities } = useCapabilities()

    const ok = await fetchCapabilities()

    expect(ok).toBe(true)
    expect(error.value).toBe('')
    expect(capabilities.value).toEqual({
      ai: true,
      whisper: false,
      ffmpeg: false,
      guest_access_enabled: false,
    })
  })
})
