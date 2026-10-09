import type { ApiBody, ApiResponse } from './contracts'

import type { components } from './generated/schema'

/**
 * API functions for application settings (tenant branding + logo upload/delete).
 */

import apiClient from './client'

// ---------------------------------------------------------------------------
// Tenant branding settings (DB-persisted, shared across all users)
// ---------------------------------------------------------------------------

export type TenantSettings = components['schemas']['OrganizationSettingsResponse']

/**
 * Fetch tenant branding settings from the backend.
 * Available to all authenticated users.
 */
export async function getTenantSettings(): Promise<TenantSettings> {
  const { data } = await apiClient.get<ApiResponse<'/api/settings', 'get'>>('/api/settings')
  return data
}

/**
 * Update tenant branding settings. Admin only.
 * Only provided fields are updated.
 *
 * @param patch - Partial branding fields to update.
 * @param accessToken - Optional explicit bearer token. Used during initial
 *   setup, when the AuthContext state has not yet propagated to the shared
 *   client's request interceptor.
 */
export async function updateTenantSettings(
  patch: ApiBody<'/api/settings', 'put'>,
  accessToken?: string,
): Promise<TenantSettings> {
  const config = accessToken ? { headers: { Authorization: `Bearer ${accessToken}` } } : undefined
  const { data } = await apiClient.put<ApiResponse<'/api/settings', 'put'>>(
    '/api/settings',
    patch,
    config,
  )
  return data
}

// ---------------------------------------------------------------------------
// Logo file upload (stored as binary blob in the database)
// ---------------------------------------------------------------------------

/**
 * Upload a company logo image. Replaces any previously uploaded logo.
 *
 * @param file - The image file to upload (PNG, JPEG, SVG, WebP, GIF; max 2 MB).
 */
export async function uploadLogo(file: File): Promise<void> {
  const formData = new FormData()
  formData.append('file', file)

  await apiClient.post<ApiResponse<'/api/settings/logo', 'post'>>('/api/settings/logo', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/**
 * Delete the currently uploaded company logo.
 */
export async function deleteLogo(): Promise<void> {
  await apiClient.delete('/api/settings/logo')
}

/**
 * Get the URL for the uploaded logo. This is a dynamic endpoint that serves
 * the logo binary from the database. Can be used directly as an image src.
 *
 * Appends a cache-busting query parameter so the browser fetches the new
 * image after an upload (the endpoint sets Cache-Control: max-age=3600).
 *
 * Returns the full URL accounting for the configured API base.
 */
export function getLogoUrl(): string {
  const base = apiClient.defaults.baseURL || ''
  return `${base}/api/settings/logo?v=${Date.now()}`
}
