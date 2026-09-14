/**
 * Guards on the translation dictionaries themselves.
 *
 * These exist because of a bug that shipped: 94 strings across both locales were written with
 * `{{name}}` while `interpolate` matches `{name}`. The regex then matched the INNER braces, so
 * every one of those strings rendered the value wrapped in literal braces — "Ordner „{Test}"
 * wirklich löschen?" instead of "Ordner „Test" wirklich löschen?". Nothing failed, no test broke,
 * and it was only found by reading the interpolation function while adding a new string.
 *
 * A convention that is only documented in a docstring is a convention that drifts, so it is
 * asserted here instead.
 */

import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { FINDING_KINDS } from '../api/digest'
import de from './de.json'
import en from './en.json'

/** Every string value in a nested dictionary, with its dotted path. */
function flatten(obj: Record<string, unknown>, prefix = ''): [string, string][] {
  const out: [string, string][] = []
  for (const [key, value] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (typeof value === 'string') {
      out.push([path, value])
    } else if (value && typeof value === 'object') {
      out.push(...flatten(value as Record<string, unknown>, path))
    }
  }
  return out
}

const LOCALES: [string, Record<string, unknown>][] = [
  ['de', de as Record<string, unknown>],
  ['en', en as Record<string, unknown>],
]

describe.each(LOCALES)('%s dictionary', (_name, dictionary) => {
  const entries = flatten(dictionary)

  it('has strings to check', () => {
    expect(entries.length).toBeGreaterThan(100)
  })

  it('uses single-brace placeholders only', () => {
    const offenders = entries.filter(([, value]) => /\{\{|\}\}/.test(value))
    expect(offenders.map(([path]) => path)).toEqual([])
  })

  it('has no unbalanced braces', () => {
    const offenders = entries.filter(([, value]) => {
      const open = (value.match(/\{/g) ?? []).length
      const close = (value.match(/\}/g) ?? []).length
      return open !== close
    })
    expect(offenders.map(([path]) => path)).toEqual([])
  })

  it('has no placeholder that interpolate would not match', () => {
    // interpolate uses /\{(\w+)\}/g. A placeholder with a space, dot or hyphen inside is
    // therefore never substituted and reaches the user verbatim.
    const offenders = entries.filter(([, value]) => {
      const placeholders = value.match(/\{[^}]*\}/g) ?? []
      return placeholders.some((p) => !/^\{\w+\}$/.test(p))
    })
    expect(offenders.map(([path]) => path)).toEqual([])
  })
})

describe('both dictionaries', () => {
  it('define the same keys', () => {
    // A key present in one locale only falls back to the raw dotted path, which shows up as
    // "teamWeek.print" in the UI rather than as an error.
    const deKeys = new Set(flatten(de as Record<string, unknown>).map(([path]) => path))
    const enKeys = new Set(flatten(en as Record<string, unknown>).map(([path]) => path))
    const onlyDe = [...deKeys].filter((key) => !enKeys.has(key))
    const onlyEn = [...enKeys].filter((key) => !deKeys.has(key))
    expect({ onlyDe, onlyEn }).toEqual({ onlyDe: [], onlyEn: [] })
  })

  it('use the same placeholders for the same key', () => {
    // A translator dropping {days} from one locale silently loses the number.
    const deEntries = new Map(flatten(de as Record<string, unknown>))
    const enEntries = new Map(flatten(en as Record<string, unknown>))
    const mismatched: string[] = []
    for (const [path, deValue] of deEntries) {
      const enValue = enEntries.get(path)
      if (enValue === undefined) continue
      const dePlaceholders = new Set(deValue.match(/\{\w+\}/g) ?? [])
      const enPlaceholders = new Set(enValue.match(/\{\w+\}/g) ?? [])
      if (
        dePlaceholders.size !== enPlaceholders.size ||
        [...dePlaceholders].some((p) => !enPlaceholders.has(p))
      ) {
        mismatched.push(path)
      }
    }
    expect(mismatched).toEqual([])
  })
})

/**
 * Every `t('a.b')` in the source must resolve in BOTH locales.
 *
 * This closes a class the other guards could not see: they compare the two
 * dictionaries against each other, so a key that is missing from BOTH is
 * consistent and passes. `interpolate` returns the key unchanged when it does not
 * resolve, so the failure renders the literal string "common.add" as a button
 * label — visible to the user, invisible to every test. Four call sites were
 * doing exactly that when this test was written.
 *
 * Asymmetry worth keeping in mind: a WRONG translation is caught by reading the
 * screen, a MISSING one only by looking at the right screen in the right locale.
 */
describe('translation keys referenced in source', () => {
  const srcDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

  function sourceFiles(dir: string): string[] {
    return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) return sourceFiles(full)
      if (!/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) return []
      return [full]
    })
  }

  const referenced = new Set<string>()
  for (const file of sourceFiles(srcDir)) {
    const text = fs.readFileSync(file, 'utf8')
    for (const line of text.split('\n')) {
      // Comments are skipped, and the reason is this guard failing on its own documentation:
      // a docstring explaining that the scan "only sees literal t('a.b') calls" was itself
      // read as a call to t('a.b'), so the suite demanded a key nobody had written. Prose
      // about translation keys is not a translation key.
      const trimmed = line.trimStart()
      if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) continue
      const code = line.split('//')[0]
      for (const match of code.matchAll(/\bt\(\s*'([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)+)'/g)) {
        referenced.add(match[1])
      }
    }
  }

  it('finds call sites to check', () => {
    // Guards the scan itself: a broken regex would make this suite vacuously green.
    expect(referenced.size).toBeGreaterThan(100)
  })

  it.each(LOCALES)('resolves every referenced key in %s', (_name, dictionary) => {
    const known = new Set(flatten(dictionary).map(([p]) => p))
    const missing = [...referenced].filter((key) => !known.has(key)).sort()
    expect(missing).toEqual([])
  })
})

/**
 * Every digest finding kind must have its sentences, in both locales.
 *
 * These keys are the one set the guard above cannot check: the panel composes them as
 * `digest.finding.${kind}.title`, and the scan only sees literal `t('a.b')` calls. Without
 * this test a new finding kind would ship rendering the raw key string as a dashboard
 * headline — which is the exact failure the German-prose-in-the-backend change was made to
 * end.
 */
describe('digest finding sentences', () => {
  it.each(LOCALES)('has a title and a detail for every kind in %s', (_name, dictionary) => {
    const known = new Set(flatten(dictionary).map(([path]) => path))
    const missing = FINDING_KINDS.flatMap((kind) =>
      ['title', 'detail']
        .map((part) => `digest.finding.${kind}.${part}`)
        .filter((key) => !known.has(key)),
    )
    expect(missing).toEqual([])
  })

  it.each(LOCALES)('has a singular detail wherever the plural uses {days} in %s', (_n, dict) => {
    // Derived from the dictionary rather than from a list of kinds, so it cannot drift: any
    // sentence that interpolates a day count needs the form for exactly one day. German
    // reads "seit 1 Tagen" otherwise, which is why the pair exists at all.
    const entries = new Map(flatten(dict))
    const missing = FINDING_KINDS.filter((kind) => {
      const plural = entries.get(`digest.finding.${kind}.detail`)
      if (plural === undefined || !plural.includes('{days}')) return false
      return !entries.has(`digest.finding.${kind}.detailOne`)
    })
    expect(missing).toEqual([])
  })
})
