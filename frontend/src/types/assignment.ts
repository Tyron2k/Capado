import type { components } from '../api/generated/schema'

/**
 * TypeScript interfaces for assignments and conflicts.
 * Corresponds to the backend schemas in app/schemas/assignment.py and app/schemas/capacity.py.
 *
 * Personal assignments carry ``start_date`` / ``end_date`` / ``allocation_percent``.
 * Infrastructure assignments carry ``start_at`` / ``end_at`` as offset-bearing
 * UTC instants (minute precision). The respective other fields remain ``null``.
 */

export type ResourceType = components['schemas']['ResourceType']

export type Assignment = components['schemas']['AssignmentResponse']

export type AssignmentCreate = components['schemas']['AssignmentCreate']

export type AssignmentUpdate = components['schemas']['AssignmentUpdate']

/** Response from POST/PUT includes warnings (e.g., capacity exceeded) */
export type AssignmentWithWarnings = components['schemas']['AssignmentCreateResponse']

export type AssignmentPreview = components['schemas']['AssignmentPreviewResponse']

/** Conflict severity derived from overload_ratio. */
export type ConflictSeverity = Conflict['severity']

/** Conflict assignment info (details about assignments involved in a conflict) */
export type ConflictAssignmentInfo = components['schemas']['ConflictAssignmentInfo']

/** A detected conflict for a resource */
export type Conflict = components['schemas']['ConflictResponse']

/** Response from GET /api/conflicts */

/** A suggested resource that could fill an unmet requirement (lightweight). */
export type UnmetRequirementSuggestion = UnmetRequirement['suggestions'][number]

/** A single unmet skill requirement for a work package. */
export type UnmetRequirement = components['schemas']['UnmetRequirementResponse']
