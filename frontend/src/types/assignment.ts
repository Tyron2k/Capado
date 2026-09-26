/**
 * TypeScript interfaces for assignments and conflicts.
 * Corresponds to the backend schemas in app/schemas/assignment.py and app/schemas/capacity.py.
 *
 * Personal assignments carry ``start_date`` / ``end_date`` / ``allocation_percent``.
 * Infrastructure assignments carry ``start_at`` / ``end_at`` as offset-bearing
 * UTC instants (minute precision). The respective other fields remain ``null``.
 */

export type ResourceType = 'personal' | 'infrastructure'

export interface Assignment {
  id: string
  resource_id: string
  resource_name?: string | null
  resource_type: ResourceType
  work_package_id: string
  work_package_name?: string | null
  project_id?: string | null
  project_name?: string | null
  start_date: string | null
  end_date: string | null
  allocation_percent: number | null
  start_at: string | null
  end_at: string | null
  /** True when the resource lacks skills required by the work package. */
  skill_mismatch: boolean
  created_at: string
  updated_at: string
}

export interface AssignmentCreate {
  resource_id: string
  resource_type: ResourceType
  work_package_id: string
  start_date?: string
  end_date?: string
  allocation_percent?: number
  start_at?: string
  end_at?: string
}

export interface AssignmentUpdate {
  resource_id?: string
  resource_type?: ResourceType
  work_package_id?: string
  start_date?: string
  end_date?: string
  allocation_percent?: number
  start_at?: string
  end_at?: string
}

/** Response from POST/PUT includes warnings (e.g., capacity exceeded) */
export interface AssignmentWithWarnings {
  assignment: Assignment
  warnings: string[]
}

export interface AssignmentPreview {
  resources: {
    resource_id: string
    resource_name: string
    resource_type: ResourceType
    conflicts_before: PreviewConflict[]
    conflicts_after: PreviewConflict[]
    capacity_days: {
      date: string
      available_percent: number
      assigned_before_percent: number
      assigned_after_percent: number
    }[]
  }[]
}

interface PreviewConflict {
  cause: 'over_allocation' | 'booking_overlap' | 'outside_availability'
  start_date: string
  end_date: string
  total_assigned_percent: number
  available_percent: number
}

/** Conflict severity derived from overload_ratio. */
export type ConflictSeverity = 'low' | 'medium' | 'high'

/** Conflict assignment info (details about assignments involved in a conflict) */
export interface ConflictAssignmentInfo {
  assignment_id: string
  work_package_id?: string
  work_package_name?: string
  project_id?: string
  project_name?: string
  resource_id?: string
  resource_name?: string
  start_date?: string | null
  end_date?: string | null
  allocation_percent?: number | null
  start_at?: string | null
  end_at?: string | null
  /** True when the resource lacks skills required by the work package. */
  skill_mismatch?: boolean
}

/** A detected conflict for a resource */
export interface Conflict {
  id: string
  resource_id: string
  resource_name?: string
  resource_type: ResourceType
  start_date: string
  end_date: string
  total_assigned_percent: number
  available_percent: number
  severity: ConflictSeverity
  overload_ratio: number | null
  detected_at: string
  assignments: ConflictAssignmentInfo[]
}

/** Response from GET /api/conflicts */
export interface ConflictListResponse {
  conflicts: Conflict[]
  total: number
}

/** A suggested resource that could fill an unmet requirement (lightweight). */
export interface UnmetRequirementSuggestion {
  resource_id: string
  resource_name: string
  resource_type: string
  group_name: string | null
  overlapping_assignments: number
}

/** A single unmet skill requirement for a work package. */
export interface UnmetRequirement {
  work_package_id: string
  work_package_name: string
  project_id: string
  project_name: string
  start_date: string
  end_date: string
  skill_name: string
  attribute_name: string | null
  resource_type: string
  required_quantity: number
  assigned_quantity: number
  gap: number
  suggestions: UnmetRequirementSuggestion[]
}
