/**
 * TypeScript types for the dashboard.
 * Based on the backend schemas in app/schemas/dashboard.py.
 */

/** Color indicator for utilization level (green = ok, yellow = warn, red = overloaded). */
export type UtilizationColor = 'green' | 'yellow' | 'red'

export interface WeeklyUtilizationResponse {
  week_start: string
  total_available: number
  total_assigned: number
  utilization: number
  overbooked: number
  color: UtilizationColor
}

export interface ProjectConflictSummary {
  id: string
  name: string
  start_date: string
  end_date: string
  conflict_count: number
}

export interface DashboardResponse {
  personal_utilization: WeeklyUtilizationResponse[]
  infrastructure_utilization: WeeklyUtilizationResponse[]
  projects: ProjectConflictSummary[]
}
