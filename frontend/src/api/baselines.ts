/**
 * API client for plan baselines.
 *
 * A baseline is a MARKER, not a lock. Freezing a plan does not prevent anyone editing
 * it — a hard freeze would simply move the next change into a spreadsheet, where
 * nobody can see it. What a baseline gives you is the ability to say later what the
 * plan looked like when it was agreed, and how far it has moved since (ADR-007).
 *
 * Reading is open to any authenticated user; freezing and deleting require admin.
 */

import apiClient from './client'

export interface Baseline {
  id: string
  name: string
  note: string | null
  created_by: string | null
  /** Whether this is the baseline the plan is compared against by default. */
  is_current: boolean
  created_at: string
}

interface BaselineCreated extends Baseline {
  /** How many rows the freeze captured — projects, work packages and assignments. */
  entry_count: number
}

/** How one entity differs from its frozen state. `changes` maps field to before/after. */
export interface EntityDiff {
  entity_type: string
  entity_id: string
  changes: Record<string, { before?: unknown; after?: unknown }>
}

/**
 * Drift of the live plan against a baseline.
 *
 * `added` and `removed` are not error states: work created after the freeze is
 * genuinely new, and work deleted is work that went away.
 */
export interface BaselineDiff {
  baseline_id: string
  has_drift: boolean
  added: EntityDiff[]
  removed: EntityDiff[]
  changed: EntityDiff[]
}

export async function getBaselines(signal?: AbortSignal): Promise<Baseline[]> {
  const { data } = await apiClient.get<Baseline[]>('/api/baselines', { signal })
  return data
}

/** Freeze the current plan. Admin only. */
export async function createBaseline(input: {
  name: string
  note?: string | null
  make_current?: boolean
}): Promise<BaselineCreated> {
  const { data } = await apiClient.post<BaselineCreated>('/api/baselines', input)
  return data
}

export async function getBaselineDiff(
  baselineId: string,
  signal?: AbortSignal,
): Promise<BaselineDiff> {
  const { data } = await apiClient.get<BaselineDiff>(`/api/baselines/${baselineId}/diff`, {
    signal,
  })
  return data
}

/** Delete a baseline. Admin only. The live plan is untouched. */
export async function deleteBaseline(baselineId: string): Promise<void> {
  await apiClient.delete(`/api/baselines/${baselineId}`)
}
