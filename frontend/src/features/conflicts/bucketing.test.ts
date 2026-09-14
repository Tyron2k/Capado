/**
 * Property-based tests for conflict bucketing domain logic.
 *
 * Verifies invariants:
 * - buildResourceBuckets groups all conflicts by resource_id
 * - worstSeverity is always the most severe among the bucket's conflicts
 * - totalDays is always >= number of conflicts (each conflict spans at least 1 day)
 * - buildProjectBuckets groups conflicts by project
 * - No conflicts are lost during bucketing
 *
 * **Validates: Requirements 6.4**
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { buildResourceBuckets, buildProjectBuckets, SEVERITY_ORDER } from './bucketing'
import type { Conflict, ConflictSeverity } from '../../types/assignment'

// --- Generators ---

const severityArb = fc.constantFrom<ConflictSeverity>('low', 'medium', 'high')
const resourceTypeArb = fc.constantFrom<'personal' | 'infrastructure'>('personal', 'infrastructure')

/** Generates a valid ISO date string. */
const isoDateArb = fc
  .tuple(
    fc.integer({ min: 2020, max: 2030 }),
    fc.integer({ min: 1, max: 12 }),
    fc.integer({ min: 1, max: 28 }),
  )
  .map(([y, m, d]) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`)

/** Generates a date range where end >= start. */
const dateRangeArb = fc
  .tuple(isoDateArb, fc.integer({ min: 0, max: 30 }))
  .map(([start, extraDays]) => {
    const startDate = new Date(start)
    const endDate = new Date(startDate.getTime() + extraDays * 86400000)
    const endStr = `${endDate.getFullYear()}-${String(endDate.getMonth() + 1).padStart(2, '0')}-${String(endDate.getDate()).padStart(2, '0')}`
    return { start, end: endStr, days: extraDays + 1 }
  })

/** Generates a conflict assignment info. */
const assignmentInfoArb = fc.record({
  assignment_id: fc.uuid(),
  work_package_id: fc.option(fc.uuid(), { nil: undefined }),
  work_package_name: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: undefined }),
  project_id: fc.option(fc.uuid(), { nil: undefined }),
  project_name: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: undefined }),
})

/** Generates a single conflict. */
const conflictArb = fc
  .tuple(
    fc.uuid(),
    fc.uuid(),
    fc.string({ minLength: 1, maxLength: 20 }),
    resourceTypeArb,
    dateRangeArb,
    fc.integer({ min: 101, max: 300 }),
    fc.integer({ min: 0, max: 100 }),
    severityArb,
    fc.option(fc.float({ min: Math.fround(1.01), max: Math.fround(3.0), noNaN: true }), {
      nil: null,
    }),
    fc.array(assignmentInfoArb, { minLength: 1, maxLength: 3 }),
  )
  .map(
    ([
      id,
      resource_id,
      resource_name,
      resource_type,
      dateRange,
      total_assigned_percent,
      available_percent,
      severity,
      overload_ratio,
      assignments,
    ]): Conflict => ({
      id,
      resource_id,
      resource_name,
      resource_type,
      start_date: dateRange.start,
      end_date: dateRange.end,
      total_assigned_percent,
      available_percent,
      severity,
      overload_ratio,
      detected_at: '2024-01-01T00:00:00Z',
      assignments,
    }),
  )

/** Generates a list of conflicts sharing some resource IDs. */
const conflictsListArb = fc.array(conflictArb, { minLength: 1, maxLength: 20 })

// --- Property Tests ---

describe('bucketing — property-based tests', () => {
  describe('buildResourceBuckets', () => {
    it('Property: every conflict appears in exactly one resource bucket', () => {
      fc.assert(
        fc.property(conflictsListArb, (conflicts) => {
          const buckets = buildResourceBuckets(conflicts)

          // Total conflicts across all buckets equals input length
          const totalInBuckets = buckets.reduce((sum, b) => sum + b.conflicts.length, 0)
          expect(totalInBuckets).toBe(conflicts.length)
        }),
        { numRuns: 50 },
      )
    })

    it('Property: each bucket groups conflicts by resource_id', () => {
      fc.assert(
        fc.property(conflictsListArb, (conflicts) => {
          const buckets = buildResourceBuckets(conflicts)

          for (const bucket of buckets) {
            for (const c of bucket.conflicts) {
              expect(c.resource_id).toBe(bucket.resource_id)
            }
          }
        }),
        { numRuns: 50 },
      )
    })

    it('Property: worstSeverity is the most severe among bucket conflicts', () => {
      fc.assert(
        fc.property(conflictsListArb, (conflicts) => {
          const buckets = buildResourceBuckets(conflicts)

          for (const bucket of buckets) {
            const expectedWorst = bucket.conflicts.reduce<ConflictSeverity>(
              (worst, c) =>
                SEVERITY_ORDER[c.severity] < SEVERITY_ORDER[worst] ? c.severity : worst,
              'low',
            )
            expect(bucket.worstSeverity).toBe(expectedWorst)
          }
        }),
        { numRuns: 50 },
      )
    })

    it('Property: totalDays >= number of conflicts (each spans at least 1 day)', () => {
      fc.assert(
        fc.property(conflictsListArb, (conflicts) => {
          const buckets = buildResourceBuckets(conflicts)

          for (const bucket of buckets) {
            expect(bucket.totalDays).toBeGreaterThanOrEqual(bucket.conflicts.length)
          }
        }),
        { numRuns: 50 },
      )
    })

    it('Property: number of unique resource_ids equals number of buckets', () => {
      fc.assert(
        fc.property(conflictsListArb, (conflicts) => {
          const buckets = buildResourceBuckets(conflicts)
          const uniqueResourceIds = new Set(conflicts.map((c) => c.resource_id))
          expect(buckets.length).toBe(uniqueResourceIds.size)
        }),
        { numRuns: 50 },
      )
    })

    it('Property: worstRatio is the maximum overload_ratio or null if all are null', () => {
      fc.assert(
        fc.property(conflictsListArb, (conflicts) => {
          const buckets = buildResourceBuckets(conflicts)

          for (const bucket of buckets) {
            const ratios = bucket.conflicts
              .map((c) => c.overload_ratio)
              .filter((r): r is number => r !== null)

            if (ratios.length === 0) {
              expect(bucket.worstRatio).toBeNull()
            } else {
              expect(bucket.worstRatio).toBe(Math.max(...ratios))
            }
          }
        }),
        { numRuns: 50 },
      )
    })
  })

  describe('buildProjectBuckets', () => {
    it('Property: every project bucket has at least one row', () => {
      fc.assert(
        fc.property(conflictsListArb, (conflicts) => {
          const buckets = buildProjectBuckets(conflicts)

          for (const bucket of buckets) {
            expect(bucket.rows.length).toBeGreaterThan(0)
            expect(bucket.resourceCount).toBe(bucket.rows.length)
          }
        }),
        { numRuns: 50 },
      )
    })

    it('Property: worstSeverity in project bucket is the most severe across its rows', () => {
      fc.assert(
        fc.property(conflictsListArb, (conflicts) => {
          const buckets = buildProjectBuckets(conflicts)

          for (const bucket of buckets) {
            let expectedWorst: ConflictSeverity = 'low'
            for (const row of bucket.rows) {
              if (SEVERITY_ORDER[row.resource.worstSeverity] < SEVERITY_ORDER[expectedWorst]) {
                expectedWorst = row.resource.worstSeverity
              }
            }
            expect(bucket.worstSeverity).toBe(expectedWorst)
          }
        }),
        { numRuns: 50 },
      )
    })
  })
})
