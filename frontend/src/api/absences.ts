/**
 * API functions for resource absences.
 */

import apiClient from './client'

/** Settled vs still a request. See the note on Absence.status. */
export type AbsenceStatus = 'provisional' | 'confirmed'

/**
 * Whether an absence was foreseeable — the only distinction planning needs.
 *
 * The cause used to be named here (vacation / sick / maintenance / training).
 * `sick` made this a health datum and the capacity calculation never used it, so
 * migration 013 collapsed it. `part_time` had already been dropped from the backend
 * with ADR-004 and only survived in this type.
 */
export type AbsenceReason = 'planned' | 'unplanned'

export interface Absence {
  id: string
  resource_id: string
  resource_type: 'personal' | 'infrastructure'
  reason: AbsenceReason
  start_date: string
  end_date: string
  allocation_percent: number
  /**
   * Whether the absence is settled or still a request.
   *
   * Both statuses reduce capacity IDENTICALLY. Counting a request as free capacity would plan
   * work against a day likely to disappear; what the status buys is knowing which capacity
   * gaps can still be renegotiated.
   */
  status: AbsenceStatus
  note: string | null
  created_at: string
  updated_at: string
}

interface AbsenceCreate {
  resource_id: string
  resource_type: 'personal' | 'infrastructure'
  reason: AbsenceReason
  start_date: string
  end_date: string
  allocation_percent?: number
  status?: AbsenceStatus
  note?: string | null
}

/** Response shape for paginated absences. */
interface AbsencesListResponse {
  items: Absence[]
  total: number
  limit: number
  offset: number
}

/** Fetch absences for a resource (paginated, returns all by default). */
export async function getAbsences(resourceId: string): Promise<Absence[]> {
  const response = await apiClient.get<AbsencesListResponse>('/api/absences', {
    params: { resource_id: resourceId, limit: 500 },
  })
  return response.data.items
}

/** Create a new absence. */
export async function createAbsence(data: AbsenceCreate): Promise<Absence> {
  const response = await apiClient.post<Absence>('/api/absences', data)
  return response.data
}

/** Delete an absence. */
export async function deleteAbsence(id: string): Promise<void> {
  await apiClient.delete(`/api/absences/${id}`)
}
