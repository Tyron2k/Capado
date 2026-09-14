/**
 * TypeScript interfaces for work packages and their skill requirements.
 * Corresponds to the backend schemas in app/schemas/project.py (WorkPackage section)
 * and app/routers/work_package_requirements.py.
 * Requirements: 5.1–5.6
 */

export interface WorkPackage {
  id: string
  project_id: string
  name: string
  start_date: string // ISO date string (YYYY-MM-DD)
  end_date: string // ISO date string (YYYY-MM-DD)
  /**
   * Duration in WORKING days, the unit the process is expressed in.
   *
   * Used to warn when the entered end date cannot hold the process. The entered date
   * is never overwritten — a derived date landing later is a warning, not a
   * correction.
   */
  lead_time_working_days: number | null
  /**
   * When the work finished, or null while it has not.
   *
   * A timestamp rather than a flag because "when did it finish" is what a delay
   * analysis asks. Sending null reopens the package, which has to stay possible.
   */
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface WorkPackageCreate {
  name: string
  start_date: string // ISO date string (YYYY-MM-DD)
  end_date: string // ISO date string (YYYY-MM-DD)
  lead_time_working_days?: number | null
}

export interface WorkPackageUpdate {
  name?: string
  start_date?: string
  end_date?: string
  lead_time_working_days?: number | null
  /** Send an ISO timestamp to complete, null to reopen, omit to leave unchanged. */
  completed_at?: string | null
}

/** Response from POST/PUT includes warnings (e.g., outside project boundaries) */
export interface WorkPackageWithWarnings {
  work_package: WorkPackage
  warnings: string[]
}

/** A skill requirement directly on a work package. */
export interface WorkPackageRequirement {
  id: string
  skill_id: string
  skill_name: string
  skill_attribute_id: string | null
  skill_attribute_name: string | null
  quantity: number
}

/**
 * A finish-to-start link between two work packages.
 *
 * One relationship type by design: start-to-start and finish-to-finish are expressible
 * by reordering the pair, and start-to-finish is almost never meant. What a plant needs
 * beyond ordering is waiting time, which `lag_working_days` covers.
 */
export interface WorkPackageDependency {
  id: string
  predecessor_id: string
  successor_id: string
  /** Working days after the predecessor ends. 0 means the next working day. */
  lag_working_days: number
}

/**
 * Both directions, because the question is directional.
 *
 * "What has to finish before this can start" is not the same question as "what is
 * waiting on this".
 */
export interface WorkPackageDependencies {
  predecessors: WorkPackageDependency[]
  successors: WorkPackageDependency[]
}
