/**
 * Root application component. Wraps the router in Mantine providers and
 * applies dynamic theming from the SettingsContext (primary color, color
 * scheme, font).
 */

import { QueryClientProvider } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { DEFAULT_THEME, MantineProvider, createTheme, useMantineColorScheme } from '@mantine/core'
import type { MantineColorsTuple } from '@mantine/core'
import { DatesProvider } from '@mantine/dates'
import { Notifications } from '@mantine/notifications'
import { RouterProvider } from 'react-router-dom'
import { router } from './router'
import { BRAND_SHADE_FACTORS, brandShade } from './utils/brand'
import { SettingsProvider, useSettings } from './context/SettingsContext'
import { createQueryClient } from './api/queryClient'
import { AuthProvider } from './context/AuthContext'
import { I18nProvider } from './i18n'

import '@mantine/core/styles.css'
import '@mantine/dates/styles.css'
import '@mantine/notifications/styles.css'
import '@mantine/charts/styles.css'

import 'dayjs/locale/de'

/** Generate a 10-shade Mantine color tuple from a single hex color. */
/**
 * Design tokens shared by both theme branches.
 *
 * Extracted because the typography block was duplicated: the hex branch and the built-in-colour
 * branch each carried its own copy, so a change to one silently applied to only half the
 * installations. Everything here is colour-independent on purpose — the primary colour comes from
 * organization_settings and is the one thing an operator controls.
 *
 * Softer radii and a defined shadow scale do more for how a dense planning tool feels than
 * transparency does, and unlike transparency they cost no contrast.
 */
const SHARED_TOKENS = {
  fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
  headings: {
    fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
    fontWeight: '700',
  },
  focusRing: 'auto' as const,
  defaultRadius: 'md' as const,
  radius: { xs: '4px', sm: '6px', md: '10px', lg: '14px', xl: '20px' },
  shadows: {
    xs: '0 1px 2px rgba(0, 0, 0, 0.06)',
    sm: '0 2px 6px rgba(0, 0, 0, 0.07)',
    md: '0 6px 16px rgba(0, 0, 0, 0.09)',
    lg: '0 12px 28px rgba(0, 0, 0, 0.11)',
    xl: '0 20px 44px rgba(0, 0, 0, 0.14)',
  },
}

/**
 * The brand palette Mantine registers. The mixing itself lives in utils/brand.ts, because the app shell
 * needs two of these shades as hex values rather than as CSS variables — see the note there.
 */
function hexToShades(hex: string): MantineColorsTuple {
  return BRAND_SHADE_FACTORS.map((factor) =>
    brandShade(hex, factor),
  ) as unknown as MantineColorsTuple
}

/** Syncs the Mantine color scheme with the settings context value. */
function ColorSchemeSync() {
  const { settings } = useSettings()
  const { setColorScheme } = useMantineColorScheme()

  useEffect(() => {
    setColorScheme(settings.colorScheme)
  }, [settings.colorScheme, setColorScheme])

  return null
}

function ThemedApp() {
  const { settings } = useSettings()

  const theme = useMemo(() => {
    const isHex = /^#[0-9a-fA-F]{6}$/.test(settings.primaryColor)
    const colorName = 'app-primary'

    if (isHex) {
      const shades = hexToShades(settings.primaryColor)
      return createTheme({
        ...SHARED_TOKENS,
        primaryColor: colorName,
        colors: { [colorName]: shades },
      })
    }

    const builtIn = settings.primaryColor in DEFAULT_THEME.colors ? settings.primaryColor : 'blue'
    return createTheme({
      ...SHARED_TOKENS,
      primaryColor: builtIn,
    })
  }, [settings.primaryColor])

  return (
    <MantineProvider theme={theme} defaultColorScheme="light">
      <ColorSchemeSync />
      <I18nProvider locale={settings.locale}>
        <DatesProvider settings={{ locale: settings.locale, firstDayOfWeek: 1 }}>
          <Notifications position="top-right" />
          <RouterProvider router={router} />
        </DatesProvider>
      </I18nProvider>
    </MantineProvider>
  )
}

function App() {
  /**
   * One client for the application's lifetime.
   *
   * Created in a ref-like `useState` initialiser rather than at module scope: a module-level client
   * is shared between test files in the same worker, so one test's cached data leaks into the next
   * and the failure looks like a flake. It must also not be recreated on render, which is what a bare
   * `createQueryClient()` in the body would do — every render would drop the whole cache.
   */
  const [queryClient] = useState(createQueryClient)

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <SettingsProvider>
          <ThemedApp />
        </SettingsProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}

export default App
