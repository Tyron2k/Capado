/**
 * API client functions for OIDC authentication endpoints.
 */

import axios from 'axios'
import { API_BASE_URL } from './config'

interface OIDCStatusResponse {
  enabled: boolean
}

/**
 * Check if OIDC login is available on the backend.
 */
export async function getOIDCStatus(): Promise<OIDCStatusResponse> {
  const response = await axios.get<OIDCStatusResponse>(`${API_BASE_URL}/auth/oidc/enabled`)
  return response.data
}

/**
 * Get the OIDC login URL (backend will redirect to the identity provider).
 */
export function getOIDCLoginUrl(): string {
  return `${API_BASE_URL}/auth/oidc/login`
}
