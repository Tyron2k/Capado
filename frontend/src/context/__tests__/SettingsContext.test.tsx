/**
 * Tests for SettingsContext: verifies localStorage persistence of user
 * preferences, backend branding fetch (including has_uploaded_logo), and
 * that partial updates merge correctly.
 */
// @vitest-environment jsdom
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'

import { createTestQueryClient } from '../../testUtils/queryClient'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import type { ReactNode } from 'react'

// The branding query waits for a session: GET /api/settings requires authentication, so firing it
// before AuthContext has restored one guarantees a 401 and a second, concurrent token refresh. These
// tests therefore need a signed-in session, not just a provider.
vi.mock('../AuthContext', () => ({
  useAuth: () => ({ isLoading: false, user: { id: 'u1', name: 'Test', role: 'admin' } }),
}))

// Mock the API module before importing the context.
vi.mock('../../api/settings', () => ({
  getTenantSettings: vi.fn().mockResolvedValue({
    company_name: 'Test Corp',
    company_subtitle: 'Capacity Planning',
    logo_url: '',
    primary_color: '#1a73e8',
    time_zone: 'America/New_York',
    has_uploaded_logo: false,
    audit_retention_months: 24,
    planning_freeze_before: null,
    scheduler_enabled: true,
    maintenance_hour: 2,
    smtp_enabled: false,
    smtp_host: '',
    smtp_port: 587,
    smtp_use_tls: true,
    smtp_username: '',
    smtp_password_set: false,
    smtp_from_address: '',
    digest_recipients: '',
    mail_config_errors: [],
    baseline_retention_months: 0,
  }),
}))

// Mock localStorage for node environment fallback.
const store: Record<string, string> = {}
const localStorageMock = {
  getItem: vi.fn((key: string) => store[key] ?? null),
  setItem: vi.fn((key: string, value: string) => {
    store[key] = value
  }),
  removeItem: vi.fn((key: string) => {
    delete store[key]
  }),
  clear: vi.fn(() => {
    for (const k of Object.keys(store)) delete store[k]
  }),
  get length() {
    return Object.keys(store).length
  },
  key: vi.fn((i: number) => Object.keys(store)[i] ?? null),
}

Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock })

// Import after mocking.
const { SettingsProvider, useSettings } = await import('../SettingsContext')

// A fresh client per wrapper: the branding read is a query now, so a shared client would leak one
// test's cached branding into the next.
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={createTestQueryClient()}>
    <SettingsProvider>{children}</SettingsProvider>
  </QueryClientProvider>
)

describe('SettingsContext', () => {
  beforeEach(() => {
    localStorageMock.clear()
    vi.clearAllMocks()
  })

  it('provides default user preferences when localStorage is empty', () => {
    const { result } = renderHook(() => useSettings(), { wrapper })
    expect(result.current.settings.colorScheme).toBe('light')
    expect(result.current.settings.locale).toBe('de')
  })

  it('loads branding from backend on mount', async () => {
    const { result } = renderHook(() => useSettings(), { wrapper })

    await waitFor(() => {
      expect(result.current.settings.companyName).toBe('Test Corp')
    })
    expect(result.current.settings.primaryColor).toBe('#1a73e8')
    expect(result.current.settings.companySubtitle).toBe('Capacity Planning')
    expect(result.current.settings.timeZone).toBe('America/New_York')
  })

  it('sets hasUploadedLogo from backend response', async () => {
    const { getTenantSettings } = await import('../../api/settings')
    vi.mocked(getTenantSettings).mockResolvedValueOnce({
      company_name: 'Logo Corp',
      company_subtitle: '',
      logo_url: '',
      primary_color: 'blue',
      time_zone: 'Europe/Berlin',
      has_uploaded_logo: true,
      audit_retention_months: 24,
      planning_freeze_before: null,
      scheduler_enabled: true,
      maintenance_hour: 2,
      smtp_enabled: false,
      smtp_host: '',
      smtp_port: 587,
      smtp_use_tls: true,
      smtp_username: '',
      smtp_password_set: false,
      smtp_from_address: '',
      digest_recipients: '',
      mail_config_errors: [],
      baseline_retention_months: 0,
    })

    const { result } = renderHook(() => useSettings(), { wrapper })

    await waitFor(() => {
      expect(result.current.hasUploadedLogo).toBe(true)
    })
  })

  it('persists user preferences to localStorage on update', () => {
    const { result } = renderHook(() => useSettings(), { wrapper })

    act(() => {
      result.current.updatePreferences({ locale: 'en' })
    })
    expect(result.current.settings.locale).toBe('en')
    expect(localStorageMock.setItem).toHaveBeenCalled()
    const lastCall = localStorageMock.setItem.mock.calls.at(-1)
    const stored = JSON.parse(lastCall?.[1] ?? '{}')
    expect(stored.locale).toBe('en')
  })

  it('loads user preferences from localStorage on mount', () => {
    store['user-preferences'] = JSON.stringify({
      colorScheme: 'dark',
      locale: 'en',
    })
    const { result } = renderHook(() => useSettings(), { wrapper })
    expect(result.current.settings.colorScheme).toBe('dark')
    expect(result.current.settings.locale).toBe('en')
  })

  it('partial preference update does not overwrite other fields', () => {
    const { result } = renderHook(() => useSettings(), { wrapper })

    act(() => {
      result.current.updatePreferences({ colorScheme: 'dark' })
    })
    act(() => {
      result.current.updatePreferences({ locale: 'en' })
    })
    expect(result.current.settings.colorScheme).toBe('dark')
    expect(result.current.settings.locale).toBe('en')
  })

  it('handles corrupted localStorage gracefully', () => {
    store['user-preferences'] = 'not-valid-json{{{'
    const { result } = renderHook(() => useSettings(), { wrapper })
    expect(result.current.settings.colorScheme).toBe('light')
    expect(result.current.settings.locale).toBe('de')
  })
})
