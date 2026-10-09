import { allPages } from './pagination'
import type { ApiBody, ApiQuery, ApiResponse } from './contracts'

import type { components } from './generated/schema'

/**
 * API functions for assignments and conflicts.
 */

import apiClient from './client'
import type { Assignment, AssignmentPreview, AssignmentWithWarnings } from '../types/assignment'

// --- Assignments ---

/** Fetch all assignments (optionally filterable). */
export async function getAssignments(
  params?: Omit<ApiQuery<'/api/assignments', 'get'>, 'limit' | 'offset'>,
  signal?: AbortSignal,
): Promise<Assignment[]> {
  return allPages(async (offset) => {
    const response = await apiClient.get<ApiResponse<'/api/assignments', 'get'>>(
      '/api/assignments',
      {
        params: { ...params, limit: 500, offset },
        signal,
      },
    )
    return response.data
  })
}

/** Create a new assignment (returns warnings). */
export async function createAssignment(
  data: ApiBody<'/api/assignments', 'post'>,
): Promise<AssignmentWithWarnings> {
  const response = await apiClient.post<ApiResponse<'/api/assignments', 'post'>>(
    '/api/assignments',
    data,
  )
  return response.data
}

/** Fetch one current assignment before calculating a suggested change. */
export async function getAssignment(id: string): Promise<Assignment> {
  const response = await apiClient.get<ApiResponse<'/api/assignments/{assignment_id}', 'get'>>(
    `/api/assignments/${id}`,
  )
  return response.data
}

/** Compare a proposed assignment with the saved plan without persisting it. */
export async function previewAssignment(
  data: ApiBody<'/api/assignments/preview', 'post'>,
): Promise<AssignmentPreview> {
  const response = await apiClient.post<ApiResponse<'/api/assignments/preview', 'post'>>(
    '/api/assignments/preview',
    data,
  )
  return response.data
}

/** Update an assignment (returns warnings). */
export async function updateAssignment(
  id: string,
  data: ApiBody<'/api/assignments/{assignment_id}', 'put'>,
): Promise<AssignmentWithWarnings> {
  const response = await apiClient.put<ApiResponse<'/api/assignments/{assignment_id}', 'put'>>(
    `/api/assignments/${id}`,
    data,
  )
  return response.data
}

/** Delete an assignment. */
export async function deleteAssignment(id: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/assignments/{assignment_id}', 'delete'>>(
    `/api/assignments/${id}`,
  )
}

// --- Conflicts ---

// --- Conflict Suggestions ---

export type ConflictSuggestion = components['schemas']['ConflictSuggestionResponse']

/** Fetch resolution suggestions for a conflict. */
export async function getConflictSuggestions(conflictId: string): Promise<ConflictSuggestion[]> {
  const response = await apiClient.get<
    ApiResponse<'/api/conflicts/{conflict_id}/suggestions', 'get'>
  >(`/api/conflicts/${conflictId}/suggestions`)
  return response.data
}

// --- Unmet Requirements ---

// --- Planning Overview (combined) ---

/** Combined planning overview response from a single endpoint. */
/** Aggregated planning figures. Not exported: only getPlanningOverview returns it, and the one screen
 * that renders it infers the type from the call. */
type PlanningOverviewData = ApiResponse<'/api/assignments/planning/overview', 'get'>

/** Fetch all planning overview data in a single request (unmet + conflicts + mismatches). */
export async function getPlanningOverview(signal?: AbortSignal): Promise<PlanningOverviewData> {
  const response = await apiClient.get<ApiResponse<'/api/assignments/planning/overview', 'get'>>(
    '/api/assignments/planning/overview',
    {
      signal,
    },
  )
  return response.data
}
