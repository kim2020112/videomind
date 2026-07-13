import { beforeEach, describe, expect, it, vi } from 'vitest'


function jsonResponse(payload, ok = true) {
  return {
    ok,
    json: vi.fn().mockResolvedValue(payload),
  }
}

describe('useAuth window sessions', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('stores the login session per window and sends it as a bearer token', async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ status: 'ok', session_id: 'window-session-a' }))
      .mockResolvedValueOnce(jsonResponse({
        logged_in: true,
        user: { id: 1, username: 'admin', role: 'admin' },
        usage: { used: 0, limit: 999999, allowed: true },
      }))

    const { useAuth } = await import('./useAuth.js')
    const auth = useAuth()
    await auth.login('admin', 'secret')

    expect(sessionStorage.getItem('vm_session_id')).toBe('window-session-a')
    expect(auth.getAuthHeaders()).toMatchObject({
      Authorization: 'Bearer window-session-a',
    })
    expect(global.fetch.mock.calls[1][1].headers).toMatchObject({
      Authorization: 'Bearer window-session-a',
    })
  })

  it('restores a window session after a module reload', async () => {
    sessionStorage.setItem('vm_session_id', 'restored-window-session')

    const { useAuth } = await import('./useAuth.js')
    const auth = useAuth()

    expect(auth.getAuthHeaders()).toMatchObject({
      Authorization: 'Bearer restored-window-session',
    })
    expect(auth.getAuthQueryParams().get('session_id')).toBe('restored-window-session')
  })

  it('captures a legacy cookie session into the current window', async () => {
    localStorage.setItem('vm_guest_id', 'guest-device-id')
    localStorage.setItem('vm_guest_sig', 'guest-signature')
    global.fetch = vi.fn().mockResolvedValue(jsonResponse({
      logged_in: true,
      session_id: 'legacy-cookie-session',
      user: { id: 2, username: 'legacy-user', role: 'user' },
      usage: { used: 0, limit: 20, allowed: true },
    }))

    const { useAuth } = await import('./useAuth.js')
    const auth = useAuth()
    await auth.init()

    expect(sessionStorage.getItem('vm_session_id')).toBe('legacy-cookie-session')
    expect(auth.getAuthHeaders()).toMatchObject({
      Authorization: 'Bearer legacy-cookie-session',
    })
    expect(global.fetch).toHaveBeenCalledTimes(1)
  })

  it('logs out only the current window session', async () => {
    sessionStorage.setItem('vm_session_id', 'window-session-a')
    global.fetch = vi.fn().mockResolvedValue(jsonResponse({ status: 'ok' }))

    const { useAuth } = await import('./useAuth.js')
    const auth = useAuth()
    await auth.logout()

    expect(global.fetch).toHaveBeenCalledWith('/api/auth/logout', expect.objectContaining({
      headers: expect.objectContaining({ Authorization: 'Bearer window-session-a' }),
    }))
    expect(sessionStorage.getItem('vm_session_id')).toBeNull()
  })

  it('stays logged out after refreshing a window with a conflicting shared cookie', async () => {
    localStorage.setItem('vm_guest_id', 'guest-device-id')
    localStorage.setItem('vm_guest_sig', 'guest-signature')
    sessionStorage.setItem('vm_session_id', 'window-session-a')
    global.fetch = vi.fn().mockResolvedValue(jsonResponse({ status: 'ok' }))

    let module = await import('./useAuth.js')
    await module.useAuth().logout()

    vi.resetModules()
    global.fetch = vi.fn().mockResolvedValue(jsonResponse({
      logged_in: false,
      user: null,
      usage: { used: 0, limit: 5, allowed: true },
    }))
    module = await import('./useAuth.js')
    const auth = module.useAuth()
    await auth.init()

    expect(global.fetch).toHaveBeenCalledWith('/api/auth/me', expect.objectContaining({
      headers: expect.objectContaining({
        'X-Session-Mode': 'guest',
      }),
    }))
    expect(auth.getAuthQueryParams().get('session_mode')).toBe('guest')
    expect(auth.user.value).toBeNull()
  })

  it('does not retry through a shared cookie after a window session expires', async () => {
    vi.useFakeTimers()
    localStorage.setItem('vm_guest_id', 'guest-device-id')
    localStorage.setItem('vm_guest_sig', 'guest-signature')
    sessionStorage.setItem('vm_session_id', 'expired-window-session')
    global.fetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ logged_in: false, user: null }))
      .mockResolvedValueOnce(jsonResponse({
        logged_in: true,
        user: { id: 2, username: 'other-user', role: 'user' },
      }))

    const { useAuth } = await import('./useAuth.js')
    const auth = useAuth()
    const initializing = auth.init()
    await vi.runAllTimersAsync()
    await initializing

    expect(global.fetch).toHaveBeenCalledTimes(1)
    expect(auth.user.value).toBeNull()
    vi.useRealTimers()
  })
})
