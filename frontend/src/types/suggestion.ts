/**
 * TypeScript types for resource suggestions.
 * Based on the backend schema in app/schemas/suggestion.py.
 */

export type AvailabilityStatus = 'available' | 'partially_available' | 'unavailable'

export interface ResourceSuggestion {
  resource_id: string
  resource_name: string
  /**
   * Comma-separated summary of matrix qualifications
   * (e.g. "Series Alpha/Electrical, Series Beta/Mechanical"). Empty if the person
   * has no matrix entries.
   */
  qualification_summary: string
  department: string
  availability_status: AvailabilityStatus
  average_free_capacity: number
  reason: string
}

export interface SuggestionParams {
  start_date: string
  end_date: string
  allocation_percent: number
}
