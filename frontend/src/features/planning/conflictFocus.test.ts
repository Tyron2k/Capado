import { describe, expect, it } from 'vitest'
import type { Assignment, Conflict } from '../../types/assignment'
import {
  matchesFocusedConflict,
  matchesFocusedMismatch,
  parseConflictFocus,
  planningConflictUrl,
} from './conflictFocus'

const painting = {
  available_percent: 0,
  detected_at: '',
  end_date: '',
  overload_ratio: null,
  resource_name: null,
  start_date: '',
  total_assigned_percent: 0,
  id: 'conflict-1',
  resource_id: 'anna',
  assignments: [
    {
      allocation_percent: null,
      end_at: null,
      end_date: null,
      project_name: null,
      resource_id: null,
      resource_name: null,
      skill_mismatch: false,
      start_at: null,
      start_date: null,
      work_package_name: null,
      assignment_id: 'assignment-1',
      project_id: 'project-1',
      work_package_id: 'painting',
    },
    {
      allocation_percent: null,
      end_at: null,
      end_date: null,
      project_name: null,
      resource_id: null,
      resource_name: null,
      skill_mismatch: false,
      start_at: null,
      start_date: null,
      work_package_name: null,
      assignment_id: 'assignment-2',
      project_id: 'project-1',
      work_package_id: 'coating',
    },
  ],
} as Conflict

const otherConflict = {
  available_percent: 0,
  detected_at: '',
  end_date: '',
  overload_ratio: null,
  resource_name: null,
  start_date: '',
  total_assigned_percent: 0,
  id: 'conflict-2',
  resource_id: 'bernd',
  assignments: [
    {
      allocation_percent: null,
      end_at: null,
      end_date: null,
      project_name: null,
      resource_id: null,
      resource_name: null,
      skill_mismatch: false,
      start_at: null,
      start_date: null,
      work_package_name: null,
      assignment_id: 'assignment-3',
      project_id: 'project-2',
      work_package_id: 'welding',
    },
  ],
} as Conflict

const mismatch = {
  allocation_percent: null,
  created_at: '2026-01-01T00:00:00Z',
  end_at: null,
  end_date: null,
  id: '',
  project_name: null,
  resource_name: null,
  skill_mismatch: false,
  start_at: null,
  start_date: null,
  updated_at: '2026-01-01T00:00:00Z',
  work_package_name: null,
  resource_id: 'anna',
  project_id: 'project-1',
  work_package_id: 'painting',
} as Assignment

describe('Gantt conflict focus', () => {
  it('round-trips a work-package and resource link', () => {
    const url = planningConflictUrl({ workPackageId: 'painting', resourceId: 'anna' })
    expect(url).toBe('/planning?work_package=painting&resource=anna')
    expect(parseConflictFocus(new URL(url, 'http://localhost').searchParams)).toEqual({
      projectId: undefined,
      workPackageId: 'painting',
      resourceId: 'anna',
    })
  })

  it('matches only conflicts involving the selected work package', () => {
    expect(matchesFocusedConflict(painting, { workPackageId: 'painting' })).toBe(true)
    expect(matchesFocusedConflict(otherConflict, { workPackageId: 'painting' })).toBe(false)
  })

  it('narrows resource links without hiding a project badge’s other resources', () => {
    expect(matchesFocusedConflict(painting, { projectId: 'project-1' })).toBe(true)
    expect(
      matchesFocusedConflict(painting, { workPackageId: 'painting', resourceId: 'bernd' }),
    ).toBe(false)
    expect(
      matchesFocusedMismatch(mismatch, { workPackageId: 'painting', resourceId: 'anna' }),
    ).toBe(true)
    expect(matchesFocusedMismatch(mismatch, { workPackageId: 'coating' })).toBe(false)
  })

  it('keeps resource-only links working even if a conflict has no assignments', () => {
    expect(matchesFocusedConflict({ ...painting, assignments: [] }, { resourceId: 'anna' })).toBe(
      true,
    )
    expect(parseConflictFocus(new URLSearchParams())).toBeNull()
  })
})
