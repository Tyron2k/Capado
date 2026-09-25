import type { Assignment, Conflict, ConflictAssignmentInfo } from '../../types/assignment'

export interface ConflictFocus {
  projectId?: string
  workPackageId?: string
  resourceId?: string
}

export function planningConflictUrl(focus: ConflictFocus): string {
  const params = new URLSearchParams()
  if (focus.projectId) params.set('project', focus.projectId)
  if (focus.workPackageId) params.set('work_package', focus.workPackageId)
  if (focus.resourceId) params.set('resource', focus.resourceId)
  const query = params.toString()
  return query ? `/planning?${query}` : '/planning'
}

export function parseConflictFocus(params: URLSearchParams): ConflictFocus | null {
  const projectId = params.get('project') || undefined
  const workPackageId = params.get('work_package') || undefined
  const resourceId = params.get('resource') || undefined
  return projectId || workPackageId || resourceId ? { projectId, workPackageId, resourceId } : null
}

function matchesAssignment(
  assignment: Pick<Assignment | ConflictAssignmentInfo, 'project_id' | 'work_package_id'>,
  focus: ConflictFocus,
): boolean {
  return (
    (!focus.projectId || assignment.project_id === focus.projectId) &&
    (!focus.workPackageId || assignment.work_package_id === focus.workPackageId)
  )
}

export function matchesFocusedConflict(conflict: Conflict, focus: ConflictFocus): boolean {
  return (
    (!focus.resourceId || conflict.resource_id === focus.resourceId) &&
    (!focus.projectId && !focus.workPackageId
      ? true
      : conflict.assignments.some((assignment) => matchesAssignment(assignment, focus)))
  )
}

export function matchesFocusedMismatch(assignment: Assignment, focus: ConflictFocus): boolean {
  return (
    (!focus.resourceId || assignment.resource_id === focus.resourceId) &&
    matchesAssignment(assignment, focus)
  )
}
