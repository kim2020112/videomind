import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./useAuth.js', () => ({
  useAuth: () => ({
    getAuthHeaders: () => ({
      'Content-Type': 'application/json',
      Authorization: 'Bearer admin-window-session',
    }),
  }),
}))

describe('useAdminConfig authentication', () => {
  beforeEach(() => {
    vi.resetModules()
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ providers: [], active: {} }),
    })
  })

  it('sends the current window session when loading admin data', async () => {
    const { useAdminConfig } = await import('./useAdminConfig.js')
    await useAdminConfig().fetchProviders()

    expect(global.fetch).toHaveBeenCalledWith('/api/admin/ai-config', expect.objectContaining({
      headers: expect.objectContaining({ Authorization: 'Bearer admin-window-session' }),
    }))
  })
})
