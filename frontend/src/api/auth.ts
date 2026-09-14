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

export interface UserScopes {
  scope_group_ids: string[] | null
  scope_project_ids: string[] | null
}

export interface UserInfo {
  id: string
  email: string
  name: string
  role: string
  must_change_password: boolean
  scopes: UserScopes
}

export interface LoginResponse {
  access_token: string
  user: UserInfo
}

interface RefreshResponse {
  access_token: string
}

/**
 * Authenticate a user with email and password.
 * Returns the access token and user profile; the refresh token is set by the
 * server as an httpOnly cookie.
 */
export async function postLogin(email: string, password: string): Promise<LoginResponse> {
  const response = await authClient.post<LoginResponse>('auth/login', { email, password })
  return response.data
}

/**
 * Obtain a new access token. The refresh token is read from the httpOnly
 * cookie by the server and rotated into a fresh cookie.
 */
export async function postRefresh(): Promise<RefreshResponse> {
  const response = await authClient.post<RefreshResponse>('auth/refresh')
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
  await authClient.post(
    'auth/change-password',
    { old_password: oldPassword, new_password: newPassword },
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
