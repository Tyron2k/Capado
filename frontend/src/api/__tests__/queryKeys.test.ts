/**
 * THE KEY CONVENTION, ASSERTED MECHANICALLY.
 *
 * The whole invalidation layer rests on three properties of `queryKeys`, and until now all three were
 * convention held up by review:
 *
 *   1. Every level is a valid INVALIDATION PREFIX. `queryClient.invalidateQueries({ queryKey: X.all })`
 *      only reaches a key if `X.all` is a prefix of it. A key filed under the wrong domain is
 *      unreachable by the mutation that should declare it untrue — and nothing fails loudly; a screen
 *      just shows a stale value.
 *
 *   2. Every PARAMETER appears in the key. A parameterised read whose parameter is missing shares one
 *      cache entry across parameter values, so whichever call arrives first decides what the others
 *      see. This is the mistake the convention exists to prevent, and it is invisible in review of a
 *      single line.
 *
 *   3. Keys are STABLE. A builder returning a fresh object identity per call would make React Query
 *      treat two identical reads as different queries; structural equality is what saves us, so the
 *      test pins that identical arguments produce structurally identical keys.
 *
 * This is a test of the convention rather than of any one key, so it walks the tree rather than listing
 * the keys by hand — a key added later is covered without anybody remembering to add it here.
 */
import { describe, expect, it } from 'vitest'

import { queryKeys } from '../queryClient'

type KeyGroup = Record<string, unknown>

/** Representative arguments by parameter position. Values are deliberately distinguishable. */
const SAMPLE_ARGS = ['sample-id-1', 'sample-id-2', 'sample-id-3'] as const

/** Builders whose parameters are not strings, given explicit arguments. */
const EXPLICIT_ARGS: Record<string, unknown[]> = {
  'audit.entries': [{ entityType: 'assignment', limit: 50 }],
  'audit.history': ['assignment', 'a1', 50],
  'customers.list': [true],
  'resources.list': ['personal', false],
  'admin.users': [0, 25],
  'maintenance.runs': [10],
  'conflicts.resourceSearch': [
    {
      startDate: '2026-09-01',
      endDate: '2026-09-30',
      allocationPercent: 50,
      skillId: 'sk1',
      skillAttributeId: null,
    },
  ],
}

function groups(): [string, KeyGroup][] {
  return Object.entries(queryKeys as Record<string, KeyGroup>)
}

function builders(groupName: string, group: KeyGroup): [string, (...a: unknown[]) => unknown[]][] {
  return Object.entries(group)
    .filter(([name, value]) => name !== 'all' && typeof value === 'function')
    .map(([name, fn]) => [`${groupName}.${name}`, fn as (...a: unknown[]) => unknown[]])
}

function argsFor(path: string, fn: (...a: unknown[]) => unknown[]): unknown[] {
  return EXPLICIT_ARGS[path] ?? SAMPLE_ARGS.slice(0, fn.length)
}

describe('the query key convention', () => {
  it('gives every group an `all` prefix', () => {
    for (const [name, group] of groups()) {
      expect(Array.isArray(group.all), `${name}.all must be an array`).toBe(true)
      expect((group.all as unknown[]).length, `${name}.all must be a single segment`).toBe(1)
    }
  })

  it('makes `all` a prefix of every key in its group', () => {
    for (const [groupName, group] of groups()) {
      const all = group.all as unknown[]
      for (const [path, fn] of builders(groupName, group)) {
        const key = fn(...argsFor(path, fn))
        expect(key.slice(0, all.length), `${path} must start with ${JSON.stringify(all)}`).toEqual(
          all,
        )
      }
    }
  })

  it('names a kind after the domain, so the middle level is also a usable prefix', () => {
    for (const [groupName, group] of groups()) {
      for (const [path, fn] of builders(groupName, group)) {
        const key = fn(...argsFor(path, fn))
        expect(key.length, `${path} needs at least [domain, kind]`).toBeGreaterThanOrEqual(2)
        expect(typeof key[1], `${path}'s kind must be a string`).toBe('string')
      }
    }
  })

  it('puts every parameter in the key', () => {
    for (const [groupName, group] of groups()) {
      for (const [path, fn] of builders(groupName, group)) {
        const args = argsFor(path, fn)
        if (args.length === 0) continue
        const key = fn(...args)
        const serialised = JSON.stringify(key)
        for (const arg of args) {
          // Objects are compared by their serialised form: what matters is that the parameter reached
          // the key, not how it was spelled there.
          const needle = typeof arg === 'object' && arg !== null ? JSON.stringify(arg) : String(arg)
          expect(
            serialised.includes(
              typeof arg === 'object' && arg !== null ? needle.slice(1, -1) : needle,
            ),
            `${path} drops parameter ${needle} — two parameter values would share one cache entry`,
          ).toBe(true)
        }
      }
    }
  })

  it('returns structurally identical keys for identical arguments', () => {
    for (const [groupName, group] of groups()) {
      for (const [path, fn] of builders(groupName, group)) {
        const args = argsFor(path, fn)
        expect(fn(...args), `${path} must be stable across calls`).toEqual(fn(...args))
      }
    }
  })

  it('distinguishes different parameter values', () => {
    for (const [groupName, group] of groups()) {
      for (const [path, fn] of builders(groupName, group)) {
        if (fn.length === 0 || EXPLICIT_ARGS[path]) continue
        const a = fn(...SAMPLE_ARGS.slice(0, fn.length))
        const b = fn(...SAMPLE_ARGS.slice(0, fn.length).map((v) => `${v}-other`))
        expect(a, `${path} must not collapse two parameter values into one key`).not.toEqual(b)
      }
    }
  })
})
