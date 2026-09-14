/**
 * The branding read waits for a session, and that is a measured decision rather than caution.
 *
 * `GET /api/settings` requires authentication ON PURPOSE — its docstring says branding must render for a
 * user who still has to change their password. Firing it before AuthContext has restored the session
 * therefore guarantees a 401, and the shared client answers a 401 by refreshing the token, while
 * AuthContext is already refreshing on mount through a path the interceptor cannot see. Every page load
 * produced one doomed request and one extra, concurrent token refresh.
 *
 * That extra refresh replays a refresh token the first one has just rotated. It survives only because the
 * backend tolerates a replay inside a ten-second grace window; outside that window a replay is treated as
 * theft and revokes the token family. Measured before and after on the backend access log: the 401 is gone
 * and `GET /api/settings` now succeeds on its first attempt.
 *
 * Nothing is lost by waiting. Branding CANNOT load without a session, so the defaults render during that
 * window either way — which is exactly what this test pins, because the obvious "improvement" is to drop
 * the condition so branding loads sooner, and it cannot.
 */
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import { createTestQueryClient } from '../../testUtils/queryClient'

const getTenantSettings = vi.fn()
vi.mock('../../api/settings', () => ({
  getTenantSettings: (...args: unknown[]) => getTenantSettings(...args),
  updateTenantSettings: vi.fn(),
  uploadLogo: vi.fn(),
  deleteLogo: vi.fn(),
}))

/** Swapped per test, so one file can render both the signed-in and the not-yet-signed-in case. */
let authState: { isLoading: boolean; user: { id: string } | null } = {
  isLoading: false,
  user: { id: 'u1' },
}
vi.mock('../AuthContext', () => ({
  useAuth: () => authState,
}))

const { SettingsProvider, useSettings } = await import('../SettingsContext')

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={createTestQueryClient()}>
      <SettingsProvider>{children}</SettingsProvider>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  getTenantSettings.mockReset()
  getTenantSettings.mockResolvedValue({
    company_name: 'Werk Nord',
    company_subtitle: 'Kapazitätsplanung',
    logo_url: '',
    primary_color: '#0d9488',
    has_uploaded_logo: false,
    audit_retention_months: 24,
    baseline_retention_months: 0,
    planning_freeze_before: null,
    scheduler_enabled: true,
    maintenance_hour: 2,
    smtp_password_set: false,
    mail_config_errors: [],
  })
})

describe('branding waits for the session', () => {
  it('does not request settings while the session is still being restored', async () => {
    authState = { isLoading: true, user: null }

    const { result } = renderHook(() => useSettings(), { wrapper })

    // Give the query every chance to fire. A doomed request is worse than a late one: it costs a 401 and
    // provokes a second token refresh that replays a just-rotated refresh token.
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(getTenantSettings).not.toHaveBeenCalled()

    // The defaults render meanwhile, which is what makes waiting free.
    expect(result.current.settings.companyName).toBe('Capado')
  })

  it('does not request settings when nobody is signed in', async () => {
    authState = { isLoading: false, user: null }

    renderHook(() => useSettings(), { wrapper })

    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(getTenantSettings).not.toHaveBeenCalled()
  })

  it('requests settings once the session exists', async () => {
    authState = { isLoading: false, user: { id: 'u1' } }

    const { result } = renderHook(() => useSettings(), { wrapper })

    await waitFor(() => expect(result.current.settings.companyName).toBe('Werk Nord'))
    expect(getTenantSettings).toHaveBeenCalledTimes(1)
  })
})
