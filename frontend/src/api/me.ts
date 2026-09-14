/**
 * What the signed-in person may read about themselves.
 *
 * There is deliberately no resource id in any of these calls: the backend takes it from the
 * caller's own account. A client function that accepted one would invite a caller to pass
 * somebody else's.
 */

import apiClient from './client'
import type { Absence } from './absences'
import type { Assignment } from '../types/assignment'
import type { ResourceSkillAssignment } from '../types/skill'

export interface MyPlan {
  resource_id: string
  assignments: Assignment[]
  assignment_total: number
  absences: Absence[]
  absence_total: number
  skills: ResourceSkillAssignment[]
}

/** Raised when the account is not linked to a scheduled person (HTTP 409). */
export class NoLinkedResourceError extends Error {
  constructor() {
    super('This account is not linked to a scheduled person')
    this.name = 'NoLinkedResourceError'
  }
}

/**
 * Fetch the caller's own plan.
 *
 * Translates the backend's 409 into a named error rather than letting it surface as a generic
 * request failure: "nobody has linked your account yet" is a state the page has to render
 * differently from "the request went wrong", and an empty plan is a third thing again.
 */
export async function getMyPlan(): Promise<MyPlan> {
  try {
    // The '/api' prefix is NOT optional: apiClient has an empty baseURL, so every path here is the
    // real URL. Without it the request is caught by the frontend's catch-all route, which answers 200
    // with index.html — a "successful" response whose body has none of these fields, so the page
    // crashes on plan.assignments.length instead of failing visibly.
    const response = await apiClient.get<MyPlan>('/api/me/plan')
    return response.data
  } catch (error) {
    if (
      typeof error === 'object' &&
      error !== null &&
      'response' in error &&
      (error as { response?: { status?: number } }).response?.status === 409
    ) {
      throw new NoLinkedResourceError()
    }
    throw error
  }
}
