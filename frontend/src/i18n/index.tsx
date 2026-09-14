/**
 * Lightweight i18n system. Provides a `useTranslation` hook that returns
 * a `t(key)` function resolving dot-notation keys against the active
 * locale's JSON dictionary. Supports simple `{placeholder}` interpolation.
 */

import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react'
import de from './de.json'
import en from './en.json'

export type Locale = 'de' | 'en'

const DICTIONARIES: Record<Locale, Record<string, unknown>> = { de, en }

function resolve(obj: Record<string, unknown>, path: string): string {
  const parts = path.split('.')
  let current: unknown = obj
  for (const part of parts) {
    if (current == null || typeof current !== 'object') return path
    current = (current as Record<string, unknown>)[part]
  }
  return typeof current === 'string' ? current : path
}

function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (_, key) => String(params[key] ?? `{${key}}`))
}

interface I18nContextValue {
  locale: Locale
  t: (key: string, params?: Record<string, string | number>) => string
}

const I18nContext = createContext<I18nContextValue>({
  locale: 'de',
  t: (key) => key,
})

interface I18nProviderProps {
  locale: Locale
  children: ReactNode
}

export function I18nProvider({ locale, children }: I18nProviderProps) {
  const dict = DICTIONARIES[locale] ?? DICTIONARIES.de

  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => {
      const raw = resolve(dict, key)
      return interpolate(raw, params)
    },
    [dict],
  )

  const value = useMemo(() => ({ locale, t }), [locale, t])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

/**
 * Hook to access the i18n context. Returns the active locale and a `t(key)` function
 * for resolving translation keys with optional parameter interpolation.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useTranslation() {
  return useContext(I18nContext)
}
