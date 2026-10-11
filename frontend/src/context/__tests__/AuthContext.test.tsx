/**
 * Tests for the AuthContext provider (httpOnly refresh-cookie flow).
 *
 * Covers:
 * - Initial state has user=null and isLoading=true
 * - After mount with no valid refresh cookie, isLoading becomes false and
 *   user stays null
 * - login() sets the access token and user in memory (no client-side token
 *   storage — the refresh token lives in an httpOnly cookie)
 * - logout() clears user/token and calls the server logout
 *
 * Mocks: auth API functions (postLogin, postRefresh, postLogout),
 *        api/client (setAuthInterceptorHandlers)
 */

// @vitest-environment jsdom

import { renderHook, act, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { StrictMode, type ReactNode } from 'react'

// --- Module mocks ---

vi.mock('../../api/auth', () => ({
  postLogin: vi.fn(),
  postRefresh: vi.fn(),
  postLogout: vi.fn(),
}))

vi.mock('../../api/client', () => ({
  setAuthInterceptorHandlers: vi.fn(),
}))

// Import after mocks
const { postLogin, postRefresh, postLogout } = await import('../../api/auth')
const { AuthProvider, useAuth } = await import('../AuthContext')

const mockedPostLogin = vi.mocked(postLogin)
const mockedPostRefresh = vi.mocked(postRefresh)
const mockedPostLogout = vi.mocked(postLogout)

// --- Helpers ---

/** Creates a fake JWT token with the given payload. */
function fakeJwt(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const body = btoa(JSON.stringify(payload))
  const sig = 'fake-signature'
  return `${header}.${body}.${sig}`
}

const testUserPayload = {
  sub: 'user-123',
  email: 'alice@example.com',
  name: 'Alice Test',
  role: 'editor',
  must_change_password: false,
  exp: Math.floor(Date.now() / 1000) + 3600,
  scopes: {
    scope_group_ids: null,
    scope_project_ids: null,
  },
}

const fakeAccessToken = fakeJwt(testUserPayload)

const loginUser = {
  id: 'user-123',
  email: 'alice@example.com',
  name: 'Alice Test',
  role: 'editor',
  must_change_password: false,
  scopes: {
    scope_group_ids: null,
    scope_project_ids: null,
  },
}

const wrapper = ({ children }: { children: ReactNode }) => <AuthProvider>{children}</AuthProvider>

// --- Tests ---

describe('AuthContext', () => {
  afterEach(() => vi.useRealTimers())
  beforeEach(() => {
    vi.clearAllMocks()
    // Default: no valid refresh cookie → mount refresh rejects.
    mockedPostRefresh.mockRejectedValue(new Error('no cookie'))
  })

  it('initial state has user=null and isLoading=true', () => {
    const { result } = renderHook(() => useAuth(), { wrapper })

    // On the very first render, before the mount refresh resolves.
    expect(result.current.isLoading).toBe(true)
    expect(result.current.user).toBeNull()
  })

  it('after mount with no valid refresh cookie, user stays null', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.user).toBeNull()
    expect(result.current.accessToken).toBeNull()
  })

  it('login() sets the access token and user in memory', async () => {
    mockedPostLogin.mockResolvedValue({
      access_token: fakeAccessToken,
      user: loginUser,
    })

    const { result } = renderHook(() => useAuth(), { wrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    await act(async () => {
      await result.current.login('alice@example.com', 'password123')
    })

    expect(result.current.user?.email).toBe('alice@example.com')
    expect(result.current.user?.role).toBe('editor')
    expect(result.current.accessToken).toBe(fakeAccessToken)
    // Refresh token is an httpOnly cookie — postLogin carries no refresh_token.
    expect(mockedPostLogin).toHaveBeenCalledWith('alice@example.com', 'password123')
  })

  it('logout() clears user/token and calls server logout', async () => {
    mockedPostLogin.mockResolvedValue({
      access_token: fakeAccessToken,
      user: loginUser,
    })
    mockedPostLogout.mockResolvedValue(undefined)

    const { result } = renderHook(() => useAuth(), { wrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    await act(async () => {
      await result.current.login('alice@example.com', 'password123')
    })
    expect(result.current.user).not.toBeNull()

    act(() => {
      result.current.logout()
    })

    expect(result.current.user).toBeNull()
    expect(result.current.accessToken).toBeNull()
    // Server-side revocation is best-effort and takes no argument (cookie-based).
    expect(mockedPostLogout).toHaveBeenCalledWith()
  })

  it('deduplicates bootstrap, manual refresh and StrictMode effect replay', async () => {
    let resolve!: (value: { access_token: string }) => void
    mockedPostRefresh.mockReturnValue(
      new Promise((done) => {
        resolve = done
      }),
    )
    const strictWrapper = ({ children }: { children: ReactNode }) => (
      <StrictMode>
        <AuthProvider>{children}</AuthProvider>
      </StrictMode>
    )
    const { result } = renderHook(() => useAuth(), { wrapper: strictWrapper })
    let pending!: Promise<string | null>
    act(() => {
      pending = result.current.refresh()
    })
    expect(mockedPostRefresh).toHaveBeenCalledTimes(1)
    await act(async () => {
      resolve({ access_token: fakeAccessToken })
      await pending
    })
    expect(result.current.isLoading).toBe(false)
    expect(result.current.accessToken).toBe(fakeAccessToken)
  })

  it('keeps the scheduled refresh after the authenticated state changes', async () => {
    vi.useFakeTimers()
    const short = fakeJwt({ ...testUserPayload, exp: Math.floor(Date.now() / 1000) + 90 })
    mockedPostRefresh
      .mockResolvedValueOnce({ access_token: short })
      .mockResolvedValue({ access_token: fakeAccessToken })
    const { result } = renderHook(() => useAuth(), { wrapper })
    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current.isLoading).toBe(false)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })
    expect(mockedPostRefresh).toHaveBeenCalledTimes(2)
    expect(result.current.accessToken).toBe(fakeAccessToken)
  })

  it('does not restore a session when logout overlaps a rotating refresh', async () => {
    let resolve!: (value: { access_token: string }) => void
    mockedPostRefresh.mockReturnValue(
      new Promise((done) => {
        resolve = done
      }),
    )
    mockedPostLogout.mockResolvedValue(undefined)
    const { result } = renderHook(() => useAuth(), { wrapper })
    act(() => result.current.logout())
    await act(async () => {
      resolve({ access_token: fakeAccessToken })
      await Promise.resolve()
    })
    expect(result.current.user).toBeNull()
    expect(result.current.accessToken).toBeNull()
    expect(mockedPostLogout).toHaveBeenCalledTimes(1)
  })
})
