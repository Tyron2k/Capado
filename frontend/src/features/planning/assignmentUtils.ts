/**
 * Pure utility functions for the assignments panel.
 * Extracted for testability.
 */

import type { Assignment, AssignmentCreate } from '../../types/assignment'
import { formatDate, localDateTimeToUtc, toIsoDate } from '../../utils/date'
import type { AssignmentFormValues } from './AssignmentForm'

function requireUtc(value: Date | string, timeZone: string): string {
  const instant = localDateTimeToUtc(value, timeZone)
  if (!instant) throw new Error('Local booking time is ambiguous or nonexistent')
  return instant
}

export function toAssignmentPayload(
  values: AssignmentFormValues,
  timeZone = 'Europe/Berlin',
): AssignmentCreate {
  timeZone = values.booking_time_zone ?? timeZone
  return values.resource_type === 'personal'
    ? {
        resource_id: values.resource_id,
        resource_type: values.resource_type,
        work_package_id: values.work_package_id,
        start_date: toIsoDate(values.start_date!),
        end_date: toIsoDate(values.end_date!),
        allocation_percent: values.allocation_percent,
      }
    : {
        resource_id: values.resource_id,
        resource_type: values.resource_type,
        work_package_id: values.work_package_id,
        start_at: requireUtc(values.start_at!, timeZone),
        end_at: requireUtc(values.end_at!, timeZone),
      }
}

interface WorkPackageGroup {
  wp_name: string
  wp_id: string
  assignments: Assignment[]
}

interface ProjectGroup {
  project_name: string
  project_id: string
  workPackages: WorkPackageGroup[]
}

/**
 * Parse structured warning strings from the backend and render them
 * using translated templates. Falls back to raw string for unknown formats.
 */
export function formatWarning(
  warning: string,
  t: (key: string, params?: Record<string, string | number>) => string,
): string {
  if (warning.startsWith('capacity_exceeded|')) {
    const params: Record<string, string> = {}
    for (const part of warning.split('|').slice(1)) {
      const [key, value] = part.split('=')
      if (key && value) params[key] = value
    }
    const days = Number(params.days) || 1
    const from = params.from ? formatDate(params.from) : ''
    const to = params.to ? formatDate(params.to) : ''
    const maxUtil = params.max_util ?? '0'
    if (days === 1) {
      return t('planning.capacityExceededSingle', { date: from, maxUtil })
    }
    return t('planning.capacityExceededMulti', { days, from, to, maxUtil })
  }
  return warning
}

/**
 * Group assignments by project and work package for the grouped table view.
 * Sorted by project name, then work package name.
 */
export function groupByProjectAndWorkPackage(assignments: Assignment[]): ProjectGroup[] {
  const projectMap = new Map<string, ProjectGroup>()

  for (const a of assignments) {
    const projId = a.project_id ?? '__none__'
    const projName = a.project_name ?? '—'
    const wpId = a.work_package_id
    const wpName = a.work_package_name ?? '—'

    let proj = projectMap.get(projId)
    if (!proj) {
      proj = { project_name: projName, project_id: projId, workPackages: [] }
      projectMap.set(projId, proj)
    }
    let wp = proj.workPackages.find((w) => w.wp_id === wpId)
    if (!wp) {
      wp = { wp_name: wpName, wp_id: wpId, assignments: [] }
      proj.workPackages.push(wp)
    }
    wp.assignments.push(a)
  }

  return Array.from(projectMap.values()).sort((a, b) =>
    a.project_name.localeCompare(b.project_name, 'de'),
  )
}
