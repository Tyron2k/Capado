/**
 * API functions for application settings (tenant branding + logo upload/delete).
 */

import apiClient from './client'

// ---------------------------------------------------------------------------
// Tenant branding settings (DB-persisted, shared across all users)
// ---------------------------------------------------------------------------

export interface TenantSettings {
  company_name: string
  company_subtitle: string
  logo_url: string
  primary_color: string
  /** IANA zone used to display and enter infrastructure booking times. */
  time_zone: string
  has_uploaded_logo: boolean
  /**
   * Months of audit history to keep. 0 keeps everything.
   *
   * Setting this deletes nothing on its own — the backend's prune_audit_log job
   * applies it. A value here with no scheduled job is a promise, not a mechanism.
   */
  audit_retention_months: number
  /**
   * Months of plan baselines to keep. 0 keeps everything, and is the default —
   * deliberately unlike the audit log, because a baseline is a record somebody chose
   * to create rather than one that accumulated by itself.
   */
  baseline_retention_months: number
  /**
   * First day that may still be edited, or null for no freeze.
   *
   * EXCLUSIVE: the named day is still editable. Sending null LIFTS the freeze, which is why
   * the update payload has to distinguish "not mentioned" from "explicitly null".
   */
  planning_freeze_before: string | null
  scheduler_enabled: boolean
  /** Hour after which maintenance runs, in the SERVER's clock — normally UTC. */
  maintenance_hour: number
  smtp_enabled: boolean
  smtp_host: string
  smtp_port: number
  smtp_use_tls: boolean
  smtp_username: string
  /**
   * Whether a password is stored — the value itself is never sent.
   *
   * Rendering the password into the DOM would leak it to anybody looking over a shoulder, which
   * is a realistic threat. A boolean lets the operator leave the field blank instead of retyping.
   */
  smtp_password_set: boolean
  smtp_from_address: string
  digest_recipients: string
  /**
   * What is wrong with the mail configuration right now.
   *
   * Computed on READ, not only on save: a configuration that was valid when saved can become
   * incomplete later, and the operator should see that on the page rather than infer it from a
   * digest that never arrived.
   */
  mail_config_errors: string[]
}

/**
 * Fetch tenant branding settings from the backend.
 * Available to all authenticated users.
 */
export async function getTenantSettings(): Promise<TenantSettings> {
  const { data } = await apiClient.get<TenantSettings>('/api/settings')
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
  patch: Partial<Omit<TenantSettings, 'has_uploaded_logo'>>,
  accessToken?: string,
): Promise<TenantSettings> {
  const config = accessToken ? { headers: { Authorization: `Bearer ${accessToken}` } } : undefined
  const { data } = await apiClient.put<TenantSettings>('/api/settings', patch, config)
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

  await apiClient.post('/api/settings/logo', formData, {
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
