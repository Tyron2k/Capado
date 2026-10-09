import { allPages } from './pagination'
import type { ApiBody, ApiResponse } from './contracts'

import type { components } from './generated/schema'

/**
 * API functions for resource absences.
 */

import apiClient from './client'

/** Settled vs still a request. See the note on Absence.status. */
export type AbsenceStatus = components['schemas']['AbsenceStatus']

/**
 * Whether an absence was foreseeable — the only distinction planning needs.
 *
 * The cause used to be named here (vacation / sick / maintenance / training).
 * `sick` made this a health datum and the capacity calculation never used it, so
 * migration 013 collapsed it. `part_time` had already been dropped from the backend
 * with ADR-004 and only survived in this type.
 */
export type AbsenceReason = components['schemas']['AbsenceReason']

export type Absence = components['schemas']['AbsenceResponse']

/** Response shape for paginated absences. */

/** Fetch absences for a resource (paginated, returns all by default). */
export async function getAbsences(resourceId: string): Promise<Absence[]> {
  return allPages(async (offset) => {
    const response = await apiClient.get<ApiResponse<'/api/absences', 'get'>>('/api/absences', {
      params: { resource_id: resourceId, limit: 500, offset },
    })
    return response.data
  })
}

/** Create a new absence. */
export async function createAbsence(data: ApiBody<'/api/absences', 'post'>): Promise<Absence> {
  const response = await apiClient.post<ApiResponse<'/api/absences', 'post'>>('/api/absences', data)
  return response.data
}

/** Delete an absence. */
export async function deleteAbsence(id: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/absences/{absence_id}', 'delete'>>(`/api/absences/${id}`)
}
