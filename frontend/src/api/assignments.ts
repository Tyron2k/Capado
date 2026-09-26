/**
 * API functions for assignments and conflicts.
 */

import apiClient from './client'
import type {
  Assignment,
  AssignmentCreate,
  AssignmentPreview,
  AssignmentUpdate,
  AssignmentWithWarnings,
  ConflictListResponse,
  UnmetRequirement,
} from '../types/assignment'

// --- Assignments ---

/** Fetch all assignments (optionally filterable). */
export async function getAssignments(
  params?: {
    resource_id?: string
    work_package_id?: string
    startDate?: string
    endDate?: string
    skillMismatch?: boolean
  },
  signal?: AbortSignal,
): Promise<Assignment[]> {
  const response = await apiClient.get<{ items: Assignment[]; total: number }>('/api/assignments', {
    params,
    signal,
  })
  return response.data.items
}

/** Create a new assignment (returns warnings). */
export async function createAssignment(data: AssignmentCreate): Promise<AssignmentWithWarnings> {
  const response = await apiClient.post<AssignmentWithWarnings>('/api/assignments', data)
  return response.data
}

/** Fetch one current assignment before calculating a suggested change. */
export async function getAssignment(id: string): Promise<Assignment> {
  const response = await apiClient.get<Assignment>(`/api/assignments/${id}`)
  return response.data
}

/** Compare a proposed assignment with the saved plan without persisting it. */
export async function previewAssignment(
  data: AssignmentCreate & { assignment_id?: string },
): Promise<AssignmentPreview> {
  const response = await apiClient.post<AssignmentPreview>('/api/assignments/preview', data)
  return response.data
}

/** Update an assignment (returns warnings). */
export async function updateAssignment(
  id: string,
  data: AssignmentUpdate,
): Promise<AssignmentWithWarnings> {
  const response = await apiClient.put<AssignmentWithWarnings>(`/api/assignments/${id}`, data)
  return response.data
}

/** Delete an assignment. */
export async function deleteAssignment(id: string): Promise<void> {
  await apiClient.delete(`/api/assignments/${id}`)
}

// --- Conflicts ---

// --- Conflict Suggestions ---

export interface ConflictSuggestion {
  type:
    'shift_forward' | 'shift_backward' | 'shift_into_window' | 'reduce_allocation' | 'swap_resource'
  assignment_id: string
  description: string
  shift_days?: number | null
  new_allocation_percent?: number | null
  target_resource_id?: string | null
  target_resource_name?: string | null
  new_start_at?: string | null
  new_end_at?: string | null
}

/** Fetch resolution suggestions for a conflict. */
export async function getConflictSuggestions(conflictId: string): Promise<ConflictSuggestion[]> {
  const response = await apiClient.get<ConflictSuggestion[]>(
    `/api/conflicts/${conflictId}/suggestions`,
  )
  return response.data
}

// --- Unmet Requirements ---

// --- Planning Overview (combined) ---

/** Combined planning overview response from a single endpoint. */
/** Aggregated planning figures. Not exported: only getPlanningOverview returns it, and the one screen
 * that renders it infers the type from the call. */
interface PlanningOverviewData {
  unmet_requirements: UnmetRequirement[]
  conflicts: ConflictListResponse['conflicts']
  mismatched_assignments: Assignment[]
}

/** Fetch all planning overview data in a single request (unmet + conflicts + mismatches). */
export async function getPlanningOverview(signal?: AbortSignal): Promise<PlanningOverviewData> {
  const response = await apiClient.get<PlanningOverviewData>('/api/assignments/planning/overview', {
    signal,
  })
  return response.data
}
