/**
 * Form state for the SMTP section.
 *
 * In its own module rather than exported from the component file: mixing component and
 * non-component exports breaks React fast refresh, which eslint enforces. Small file, but the
 * alternative is a dev-server that stops hot-reloading the settings page.
 */

import type { TenantSettings } from '../../api/settings'

export interface MailFormState {
  smtp_enabled: boolean
  smtp_host: string
  smtp_port: number | ''
  smtp_use_tls: boolean
  /** null = leave the stored password untouched. '' = clear it. */
  smtp_password: string | null
  smtp_username: string
  smtp_from_address: string
  digest_recipients: string
}

export function mailStateFrom(settings: TenantSettings): MailFormState {
  return {
    smtp_enabled: settings.smtp_enabled,
    smtp_host: settings.smtp_host,
    smtp_port: settings.smtp_port,
    smtp_use_tls: settings.smtp_use_tls,
    smtp_username: settings.smtp_username,
    // Not '' — that would clear the stored password on the first save.
    smtp_password: null,
    smtp_from_address: settings.smtp_from_address,
    digest_recipients: settings.digest_recipients,
  }
}
