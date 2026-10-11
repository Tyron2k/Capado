/**
 * Authentication context providing user state, login/logout/refresh methods,
 * and automatic token refresh scheduling. Access tokens are stored in memory
 * (never localStorage) for security. Refresh tokens live in HttpOnly cookies.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { postLogin, postLogout, postRefresh, type UserInfo } from '../api/auth'
import { setAuthInterceptorHandlers } from '../api/client'

/** Margin in milliseconds before token expiry to trigger refresh (60 seconds). */
const REFRESH_MARGIN_MS = 60_000

interface AuthContextValue {
  /** Current authenticated user, or null if not logged in. */
  user: UserInfo | null
  /** Current access token held in memory. */
  accessToken: string | null
  /** Whether the initial auth check is still in progress. */
  isLoading: boolean
  /** Authenticate with email and password. */
  login: (email: string, password: string) => Promise<UserInfo>
  /** Establish session from an access token (initial setup; refresh token is
   * already set as an httpOnly cookie by the backend). */
  loginWithTokens: (accessToken: string) => void
  /** Clear auth state and redirect to login. */
  logout: () => void
  /** Manually refresh the access token. */
  refresh: () => Promise<string | null>
  /** Clear the must_change_password flag on the current user. */
  clearMustChangePassword: () => void
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  accessToken: null,
  isLoading: true,
  login: () => Promise.reject(new Error('AuthContext not initialized')),
  loginWithTokens: () => {},
  logout: () => {},
  refresh: () => Promise.resolve(null),
  clearMustChangePassword: () => {},
})

/**
 * Decode a JWT payload to extract the expiration time.
 * Returns the exp claim in seconds, or null if decoding fails.
 */
function getTokenExp(token: string): number | null {
  try {
    const payload = token.split('.')[1]
    const decoded = JSON.parse(atob(payload))
    return typeof decoded.exp === 'number' ? decoded.exp : null
  } catch {
    return null
  }
}

/**
 * Decode user info from a JWT access token payload.
 */
function decodeUserFromToken(token: string): UserInfo | null {
  try {
    const payload = token.split('.')[1]
    const decoded = JSON.parse(atob(payload))
    if (decoded.sub && decoded.email) {
      const scopes = decoded.scopes || {}
      return {
        id: decoded.sub,
        email: decoded.email,
        name: decoded.name || decoded.email,
        role: decoded.role || 'viewer',
        must_change_password: decoded.must_change_password ?? false,
        scopes: {
          scope_group_ids: scopes.scope_group_ids || null,
          scope_project_ids: scopes.scope_project_ids || null,
        },
      }
    }
    return null
  } catch {
    return null
  }
}

/**
 * Provides authentication state and methods to the component tree.
 * On mount, restores the session through the HttpOnly refresh cookie.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null)
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const refreshFnRef = useRef<() => Promise<string | null>>(() => Promise.resolve(null))
  const refreshPromiseRef = useRef<Promise<string | null> | null>(null)
  const refreshGenerationRef = useRef(0)
  const logoutPromiseRef = useRef<Promise<void> | null>(null)

  /** Schedule a token refresh before the access token expires. */
  const scheduleRefresh = useCallback((token: string) => {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current)
    }

    const exp = getTokenExp(token)
    if (!exp) return

    const nowMs = Date.now()
    const expiresMs = exp * 1000
    const delay = Math.max(expiresMs - nowMs - REFRESH_MARGIN_MS, 0)

    refreshTimerRef.current = setTimeout(() => {
      void refreshFnRef.current()
    }, delay)
  }, [])

  /** Attempt to refresh the access token using the httpOnly refresh cookie. */
  const refreshToken = useCallback((): Promise<string | null> => {
    if (refreshPromiseRef.current) return refreshPromiseRef.current
    const generation = refreshGenerationRef.current
    const pending = (async () => {
      try {
        const response = await postRefresh()
        if (generation !== refreshGenerationRef.current) return null
        setAccessToken(response.access_token)
        const decoded = decodeUserFromToken(response.access_token)
        if (decoded) setUser(decoded)
        scheduleRefresh(response.access_token)
        return response.access_token
      } catch {
        if (generation === refreshGenerationRef.current) {
          setUser(null)
          setAccessToken(null)
        }
        return null
      }
    })()
    refreshPromiseRef.current = pending
    void pending.finally(() => {
      refreshPromiseRef.current = null
    })
    return pending
  }, [scheduleRefresh])

  // Keep the ref in sync so the timer always calls the latest version
  useEffect(() => {
    refreshFnRef.current = refreshToken
  }, [refreshToken])

  /** Authenticate with email and password. */
  const login = useCallback(
    async (email: string, password: string): Promise<UserInfo> => {
      await logoutPromiseRef.current
      const response = await postLogin(email, password)
      setUser(response.user)
      setAccessToken(response.access_token)
      scheduleRefresh(response.access_token)
      return response.user
    },
    [scheduleRefresh],
  )

  /** Establish session from an access token (initial setup). The refresh
   * token is already stored as an httpOnly cookie by the backend. */
  const loginWithTokens = useCallback(
    (newAccessToken: string) => {
      setAccessToken(newAccessToken)
      const decoded = decodeUserFromToken(newAccessToken)
      if (decoded) {
        setUser(decoded)
      }
      scheduleRefresh(newAccessToken)
    },
    [scheduleRefresh],
  )

  /** Clear all auth state and revoke the refresh cookie server-side. */
  const logout = useCallback(() => {
    refreshGenerationRef.current += 1
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current)
    }
    // A rotating refresh may set a newer cookie. Revoke that cookie after it
    // finishes, while immediately clearing the visible session.
    const pending = refreshPromiseRef.current
    logoutPromiseRef.current = pending ? pending.then(() => postLogout()) : postLogout()
    setUser(null)
    setAccessToken(null)
  }, [])

  /** Clear the must_change_password flag on the current user after a successful password change. */
  const clearMustChangePassword = useCallback(() => {
    setUser((prev) => (prev ? { ...prev, must_change_password: false } : null))
  }, [])

  /** One shared bootstrap refresh, also during StrictMode effect replay. */
  useEffect(() => {
    void refreshFnRef.current().finally(() => setIsLoading(false))
  }, [])

  // Wire up the Axios interceptor handlers so the shared client can
  // attach tokens and trigger refresh without circular imports.
  useEffect(() => {
    setAuthInterceptorHandlers({
      getToken: () => accessToken,
      refresh: refreshToken,
      onFailure: logout,
    })
  }, [accessToken, refreshToken, logout])

  // Refresh token when the browser tab regains focus.
  // Browsers throttle/pause setTimeout in background tabs, so the scheduled
  // refresh may not fire in time. This ensures the token is still valid when
  // the user returns.
  useEffect(() => {
    function handleVisibilityChange() {
      if (document.visibilityState !== 'visible') return

      const token = accessToken
      if (!token) return

      const exp = getTokenExp(token)
      if (!exp) return

      const nowMs = Date.now()
      const expiresMs = exp * 1000

      if (expiresMs - nowMs <= REFRESH_MARGIN_MS) {
        void refreshFnRef.current()
      } else {
        scheduleRefresh(token)
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [accessToken, scheduleRefresh])

  // Changing tokens must not cancel the timer just scheduled for the new
  // token. Only an actual provider teardown owns this cleanup.
  useEffect(
    () => () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
    },
    [],
  )

  const value = useMemo(
    () => ({
      user,
      accessToken,
      isLoading,
      login,
      loginWithTokens,
      logout,
      refresh: refreshToken,
      clearMustChangePassword,
    }),
    [
      user,
      accessToken,
      isLoading,
      login,
      loginWithTokens,
      logout,
      refreshToken,
      clearMustChangePassword,
    ],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

/**
 * Hook to access the authentication context.
 * Must be used within an AuthProvider.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  return useContext(AuthContext)
}
