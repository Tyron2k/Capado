/**
 * Shared Axios client instance with Bearer token injection and
 * automatic 401 refresh-retry logic.
 *
 * The access token is retrieved from a module-level getter function
 * that is set by the AuthContext at initialization time. This avoids
 * circular imports between the API client and the context.
 */

import axios, { type InternalAxiosRequestConfig } from 'axios'

const apiClient = axios.create({
  baseURL: '',
  headers: {
    'Content-Type': 'application/json',
  },
})

// ---------------------------------------------------------------------------
// Token accessor — set by AuthContext to avoid circular dependencies
// ---------------------------------------------------------------------------

let getAccessToken: () => string | null = () => null
let refreshAccessToken: () => Promise<string | null> = () => Promise.resolve(null)
let onAuthFailure: () => void = () => {}

/**
 * Configure the token accessor functions. Called once by AuthProvider on mount.
 */
export function setAuthInterceptorHandlers(handlers: {
  getToken: () => string | null
  refresh: () => Promise<string | null>
  onFailure: () => void
}) {
  getAccessToken = handlers.getToken
  refreshAccessToken = handlers.refresh
  onAuthFailure = handlers.onFailure
}

// ---------------------------------------------------------------------------
// Request interceptor — attach Bearer token
// ---------------------------------------------------------------------------

apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = getAccessToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// ---------------------------------------------------------------------------
// Response interceptor — handle 401 with refresh retry
// ---------------------------------------------------------------------------

let isRefreshing = false
let failedQueue: Array<{
  resolve: (token: string | null) => void
  reject: (error: unknown) => void
}> = []

function processQueue(token: string | null, error: unknown = null) {
  failedQueue.forEach((pending) => {
    if (error) {
      pending.reject(error)
    } else {
      pending.resolve(token)
    }
  })
  failedQueue = []
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    // Only attempt refresh on 401 and if we haven't already retried
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        // Queue this request until the refresh completes
        return new Promise((resolve, reject) => {
          failedQueue.push({
            resolve: (token) => {
              if (token) {
                originalRequest.headers.Authorization = `Bearer ${token}`
              }
              resolve(apiClient(originalRequest))
            },
            reject,
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const newToken = await refreshAccessToken()
        if (newToken) {
          originalRequest.headers.Authorization = `Bearer ${newToken}`
          processQueue(newToken)
          return apiClient(originalRequest)
        } else {
          processQueue(null, new Error('Refresh failed'))
          onAuthFailure()
          return Promise.reject(error)
        }
      } catch (refreshError) {
        processQueue(null, refreshError)
        onAuthFailure()
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    // Non-401 error handling
    if (error.response) {
      const { status, data } = error.response

      if (status === 400 || status === 422) {
        return Promise.reject(error)
      }

      if (status === 404) {
        console.error('Resource not found:', data?.detail || 'Unknown')
      }

      if (status >= 500) {
        console.error('Server error:', data?.detail || 'An unexpected error occurred.')
      }
    } else if (error.request) {
      console.error('Network error: Server is not reachable.')
    }

    return Promise.reject(error)
  },
)

export default apiClient
