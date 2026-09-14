/**
 * Pure aggregation functions for the conflict view. Separated from the
 * render component so they remain unit-testable and the page component
 * can focus on state management + UI.
 */

import type { Conflict, ConflictSeverity } from '../../types/assignment'
import { differenceInDays } from '../../utils/date'

export const SEVERITY_ORDER: Record<ConflictSeverity, number> = {
  high: 0,
  medium: 1,
  low: 2,
}

interface ResourceBucket {
  resource_id: string
  resource_name: string
  resource_type: Conflict['resource_type']
  conflicts: Conflict[]
  worstSeverity: ConflictSeverity
  worstRatio: number | null
  totalDays: number
}

interface ProjectBucket {
  project_id: string | null
  project_name: string
  rows: Array<{ resource: ResourceBucket; conflicts: Conflict[] }>
  worstSeverity: ConflictSeverity
  resourceCount: number
}

/** Inclusive number of calendar days a conflict spans (at least one). */
function spanDays(c: Conflict): number {
  const days = differenceInDays(c.end_date, c.start_date) + 1
  return Number.isFinite(days) && days > 0 ? days : 1
}

export function buildResourceBuckets(conflicts: Conflict[]): ResourceBucket[] {
  const byResource = new Map<string, ResourceBucket>()
  for (const c of conflicts) {
    let bucket = byResource.get(c.resource_id)
    if (!bucket) {
      bucket = {
        resource_id: c.resource_id,
        resource_name: c.resource_name ?? '—',
        resource_type: c.resource_type,
        conflicts: [],
        worstSeverity: c.severity,
        worstRatio: c.overload_ratio,
        totalDays: 0,
      }
      byResource.set(c.resource_id, bucket)
    }
    bucket.conflicts.push(c)
    if (SEVERITY_ORDER[c.severity] < SEVERITY_ORDER[bucket.worstSeverity]) {
      bucket.worstSeverity = c.severity
    }
    if (c.overload_ratio !== null) {
      if (bucket.worstRatio === null || c.overload_ratio > bucket.worstRatio) {
        bucket.worstRatio = c.overload_ratio
      }
    }
    bucket.totalDays += spanDays(c)
  }
  return Array.from(byResource.values())
}

export function buildProjectBuckets(conflicts: Conflict[]): ProjectBucket[] {
  // A conflict can affect multiple projects (same day, multiple
  // colliding projects on the same resource). Therefore we collect per
  // project the conflict once, even if multiple assignments are there.
  const byProject = new Map<
    string,
    { project_id: string | null; project_name: string; items: Conflict[] }
  >()
  for (const c of conflicts) {
    const projectKeys = new Set<string>()
    for (const a of c.assignments) {
      const key = a.project_id ?? ''
      if (projectKeys.has(key)) continue
      projectKeys.add(key)
      const existing = byProject.get(key) ?? {
        project_id: a.project_id ?? null,
        project_name: a.project_name ?? '— no project —',
        items: [],
      }
      existing.items.push(c)
      byProject.set(key, existing)
    }
  }

  return Array.from(byProject.values()).map(({ project_id, project_name, items }) => {
    const byResource = new Map<string, { resource: ResourceBucket; conflicts: Conflict[] }>()
    for (const conflict of items) {
      let rb = byResource.get(conflict.resource_id)
      if (!rb) {
        rb = {
          resource: {
            resource_id: conflict.resource_id,
            resource_name: conflict.resource_name ?? '—',
            resource_type: conflict.resource_type,
            conflicts: [],
            worstSeverity: conflict.severity,
            worstRatio: conflict.overload_ratio,
            totalDays: 0,
          },
          conflicts: [],
        }
        byResource.set(conflict.resource_id, rb)
      }
      rb.conflicts.push(conflict)
      if (SEVERITY_ORDER[conflict.severity] < SEVERITY_ORDER[rb.resource.worstSeverity]) {
        rb.resource.worstSeverity = conflict.severity
      }
      rb.resource.totalDays += spanDays(conflict)
    }

    const rows = Array.from(byResource.values())
    let worstSeverity: ConflictSeverity = 'low'
    for (const row of rows) {
      if (SEVERITY_ORDER[row.resource.worstSeverity] < SEVERITY_ORDER[worstSeverity]) {
        worstSeverity = row.resource.worstSeverity
      }
    }

    return {
      project_id,
      project_name,
      rows,
      worstSeverity,
      resourceCount: rows.length,
    }
  })
}

export function resourceTypeLabel(type: Conflict['resource_type']): string {
  return type === 'personal' ? 'Personal' : 'Infrastructure'
}
