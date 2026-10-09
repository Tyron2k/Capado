import type { ApiBody, ApiResponse } from './contracts'

import type { components } from './generated/schema'

/**
 * API client functions for authentication endpoints.
 * These use a separate Axios instance to avoid circular dependencies
 * with the interceptor-equipped main client.
 */

import axios from 'axios'
import { API_BASE_URL } from './config'

const authClient = axios.create({
  baseURL: API_BASE_URL,
  // Send/receive the httpOnly refresh-token cookie on auth requests.
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

export type UserInfo = components['schemas']['UserInfo']

export type LoginResponse = components['schemas']['LoginResponse']

type RefreshResponse = components['schemas']['RefreshResponse']

/**
 * Authenticate a user with email and password.
 * Returns the access token and user profile; the refresh token is set by the
 * server as an httpOnly cookie.
 */
export async function postLogin(email: string, password: string): Promise<LoginResponse> {
  const response = await authClient.post<ApiResponse<'/api/auth/login', 'post'>>('auth/login', {
    email,
    password,
  } satisfies ApiBody<'/api/auth/login', 'post'>)
  return response.data
}

/**
 * Obtain a new access token. The refresh token is read from the httpOnly
 * cookie by the server and rotated into a fresh cookie.
 */
export async function postRefresh(): Promise<RefreshResponse> {
  const response = await authClient.post<ApiResponse<'/api/auth/refresh', 'post'>>('auth/refresh')
  return response.data
}

/**
 * Change the current user's password. Requires a valid access token.
 */
export async function postChangePassword(
  oldPassword: string,
  newPassword: string,
  accessToken: string,
): Promise<void> {
  await authClient.post<ApiResponse<'/api/auth/change-password', 'post'>>(
    'auth/change-password',
    { old_password: oldPassword, new_password: newPassword } satisfies ApiBody<
      '/api/auth/change-password',
      'post'
    >,
    { headers: { Authorization: `Bearer ${accessToken}` } },
  )
}

/**
 * Revoke the refresh-token cookie (server-side logout). The server reads the
 * cookie and clears it.
 */
export async function postLogout(): Promise<void> {
  await authClient.post('auth/logout').catch(() => {
    // Best-effort: don't block logout if the server is unreachable
  })
}
