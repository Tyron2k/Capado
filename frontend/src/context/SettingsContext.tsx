/**
 * Application-wide settings context.
 *
 * Branding settings (company name, subtitle, logo URL, primary color) are
 * loaded from the backend on mount and shared across all users.
 *
 * User preferences (color scheme, locale) are stored in localStorage per
 * browser — they are personal and not synced.
 *
 * The backend response includes `has_uploaded_logo` so we know whether to
 * use the logo endpoint without an extra network request.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../api/queryClient'
import { useAuth } from './AuthContext'
import type { MantineColorScheme } from '@mantine/core'
import type { Locale } from '../i18n'
import { getTenantSettings, type TenantSettings } from '../api/settings'

/** User-local preferences stored in localStorage. */
interface UserPreferences {
  colorScheme: MantineColorScheme
  locale: Locale
  /**
   * Whether the navigation is collapsed to icons only.
   *
   * A PREFERENCE, not server state, and it belongs here for the same reason the colour scheme does: it
   * is one person's choice on one browser, there is no server copy of it, and nothing about it can go
   * stale. Storing it per user on the backend would make a shared account impossible to use — two
   * foremen on one login would fight over each other's sidebar.
   */
  navCollapsed: boolean
}

/** Combined settings shape exposed to the app. */
interface AppSettings {
  companyName: string
  companySubtitle: string
  logoUrl: string
  primaryColor: string
  timeZone: string
  colorScheme: MantineColorScheme
  locale: Locale
  navCollapsed: boolean
}

const PREFS_STORAGE_KEY = 'user-preferences'

const DEFAULT_PREFS: UserPreferences = {
  colorScheme: 'light',
  locale: 'de',
  // Expanded by default: the labels are what make the navigation learnable, and a first-time user has
  // not yet earned the shortcut of recognising twelve icons.
  navCollapsed: false,
}

const DEFAULT_BRANDING: TenantSettings = {
  company_name: 'Capado',
  company_subtitle: '',
  logo_url: '',
  primary_color: 'blue',
  time_zone: 'Europe/Berlin',
  has_uploaded_logo: false,
  audit_retention_months: 24,
  // No freeze by default: switching one on for an existing installation would start
  // refusing edits that were legal a minute earlier.
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
}

interface SettingsContextValue {
  settings: AppSettings
  /** Update user preferences (locale, colorScheme). Saved to localStorage. */
  updatePreferences: (patch: Partial<UserPreferences>) => void
  /** Reload branding from the backend (call after admin saves). */
  refreshBranding: () => Promise<void>
  hasUploadedLogo: boolean
}

const SettingsContext = createContext<SettingsContextValue>({
  settings: {
    companyName: DEFAULT_BRANDING.company_name,
    companySubtitle: DEFAULT_BRANDING.company_subtitle,
    logoUrl: DEFAULT_BRANDING.logo_url,
    primaryColor: DEFAULT_BRANDING.primary_color,
    timeZone: DEFAULT_BRANDING.time_zone,
    ...DEFAULT_PREFS,
  },
  updatePreferences: () => {},
  refreshBranding: async () => {},
  hasUploadedLogo: false,
})

function loadPrefsFromStorage(): UserPreferences {
  try {
    const raw = localStorage.getItem(PREFS_STORAGE_KEY)
    if (!raw) return DEFAULT_PREFS
    return { ...DEFAULT_PREFS, ...JSON.parse(raw) }
  } catch {
    return DEFAULT_PREFS
  }
}

/**
 * Provides application settings state and an update function to the component tree.
 * Loads branding from the backend on mount; derives hasUploadedLogo from the response.
 */
export function SettingsProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [prefs, setPrefs] = useState<UserPreferences>(loadPrefsFromStorage)

  // Persist user preferences to localStorage.
  useEffect(() => {
    localStorage.setItem(PREFS_STORAGE_KEY, JSON.stringify(prefs))
  }, [prefs])

  /**
   * BRANDING IS SERVER STATE; PREFERENCES ARE NOT. The two live in one context and must not share a
   * mechanism.
   *
   * `branding` comes from the backend, so it belongs in the cache under `settings.tenant()` — the same
   * key the settings page reads, which is what makes a saved logo appear in the header without either
   * side calling the other.
   *
   * `prefs` (colour scheme, locale) is the user's own choice, stored in localStorage and never sent
   * anywhere. It stays plain state, and putting it in the cache would be a category error: there is no
   * server copy for it to be stale against.
   *
   * The provider sits INSIDE QueryClientProvider (see App.tsx), which is what makes this possible at all
   * — a context above the client could not use a query and would have to keep the hand-rolled fetch.
   *
   * `enabled` WAITS FOR THE SESSION, and that is not caution — it removes two requests per page load.
   * `GET /api/settings` requires authentication, deliberately (see its docstring: branding must render
   * for a user who still has to change their password). Firing it before the session is restored
   * therefore guarantees a 401, and the client's interceptor answers a 401 by refreshing the token —
   * while `AuthContext` is already refreshing on mount through its own path, which the interceptor
   * cannot see. So every page load produced a doomed request and a SECOND, concurrent token refresh.
   *
   * That second refresh is safe only because the backend tolerates replay of a just-rotated refresh
   * token inside a ten-second grace window; outside it, a replay is treated as theft and revokes the
   * token family. Nothing is lost by waiting: branding cannot load without a session, so the defaults
   * below are what renders during that window either way.
   *
   * Falls back to defaults when the backend is unreachable, as before: an unbranded shell is usable and
   * an error page is not.
   */
  const { isLoading: authLoading, user } = useAuth()

  const brandingQuery = useQuery({
    queryKey: queryKeys.settings.tenant(),
    queryFn: () => getTenantSettings(),
    enabled: !authLoading && Boolean(user),
  })
  const branding: TenantSettings = brandingQuery.data ?? DEFAULT_BRANDING
  const hasUploadedLogo = branding.has_uploaded_logo

  /**
   * Kept as part of the context's contract, but it is now just an invalidation.
   *
   * Callers used it to mean "re-read the branding after I changed it". That is what invalidating the key
   * does, and it now also refreshes the settings page's own copy — where before, the page and the header
   * each had to be refreshed by their own mechanism and it was possible to do one and forget the other.
   */
  const refreshBranding = useCallback(
    () => queryClient.invalidateQueries({ queryKey: queryKeys.settings.all }),
    [queryClient],
  )

  const updatePreferences = useCallback((patch: Partial<UserPreferences>) => {
    setPrefs((prev) => ({ ...prev, ...patch }))
  }, [])

  // Merge branding + prefs into the unified AppSettings shape.
  const settings: AppSettings = useMemo(
    () => ({
      companyName: branding.company_name,
      companySubtitle: branding.company_subtitle,
      logoUrl: branding.logo_url,
      primaryColor: branding.primary_color,
      timeZone: branding.time_zone,
      colorScheme: prefs.colorScheme,
      locale: prefs.locale,
      navCollapsed: prefs.navCollapsed,
    }),
    [branding, prefs],
  )

  const value = useMemo(
    () => ({ settings, updatePreferences, refreshBranding, hasUploadedLogo }),
    [settings, updatePreferences, refreshBranding, hasUploadedLogo],
  )

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>
}

/**
 * Hook to access the application settings context.
 * Must be used within a SettingsProvider.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useSettings(): SettingsContextValue {
  return useContext(SettingsContext)
}
