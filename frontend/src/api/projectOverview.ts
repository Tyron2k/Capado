/**
 * API client for the aggregated project overview endpoint.
 */

import apiClient from './client'

/**
 * A work package whose lead time in WORKING days overruns its committed end date.
 *
 * The project is late in fact and someone has to act. The entered date is never
 * adjusted to make this go away — that would remove the signal rather than the
 * problem.
 */
export interface LateWorkPackage {
  work_package_id: string
  work_package_name: string
  /** The committed end date, unchanged. */
  entered_end: string
  /** Where the lead time actually lands. */
  derived_end: string
  /** The gap in WORKING days — the unit the process is expressed in. */
  working_days_short: number
}

/**
 * A committed delivery date the plan does not meet.
 *
 * `hidden` is the field that matters: true means the PLANNED dates meet the commitment
 * and only the recorded working-day lead times do not. Every date-based report on such a
 * project looks fine.
 */
export interface CommitmentBreach {
  committed: string
  planned_end: string
  derived_end: string | null
  working_days_short: number
  hidden: boolean
}

/**
 * A successor whose start date contradicts a dependency.
 *
 * Carries both names: a warning naming only one side cannot be acted on, because the
 * reader has to know what waits on what before deciding which date moves.
 */
export interface DependencyViolation {
  predecessor_id: string
  predecessor_name: string
  successor_id: string
  successor_name: string
  predecessor_end: string
  successor_start: string
  lag_working_days: number
  /** First day the successor may start, given the predecessor's end and the lag. */
  earliest_start: string
  working_days_short: number
}

export interface ProjectOverviewItem {
  project_id: string
  project_name: string
  start_date: string
  end_date: string
  progress_percent: number
  active_work_package_count: number
  next_deadline: string
  open_conflict_count: number
  average_resource_utilization_percent: number | null
  late_work_packages: LateWorkPackage[]
  /** Absent means nothing was promised, which is not the same as being on time. */
  commitment_breach: CommitmentBreach | null
  /** Reported, not corrected: the planner decides which side moves. */
  dependency_violations: DependencyViolation[]
  /**
   * Smallest float across the project's work packages — how much the project as a whole
   * can slip. Null when there is nothing to analyse, negative when the deadline is
   * already unreachable.
   */
  min_float_working_days: number | null
  critical_work_package_count: number
}

interface ProjectOverviewResponse {
  projects: ProjectOverviewItem[]
}

/** Fetch the aggregated project overview with progress, deadlines, and conflicts. */
export async function getProjectOverview(projectIds?: string[]): Promise<ProjectOverviewResponse> {
  const params =
    projectIds !== undefined && projectIds.length > 0
      ? { project_ids: projectIds.join(',') }
      : undefined
  const response = await apiClient.get<ProjectOverviewResponse>('/api/projects/overview', {
    params,
  })
  return response.data
}
