import type { ApiQuery, ApiResponse } from './contracts'

import type { components } from './generated/schema'

/**
 * API client for the audit trail (admin only).
 *
 * Every endpoint here requires the admin role server-side, and the page size is capped
 * at 200 by the backend. Both are deliberate disclosure controls rather than
 * performance tuning: the log holds behavioural data about named users, so an
 * unbounded query would make it a bulk analysis tool (ADR-006).
 */

import apiClient from './client'

export type AuditAction = components['schemas']['AuditAction']

/**
 * One recorded change.
 *
 * `changes` is a per-field map. On a create it holds the value each field started
 * with; on an update it holds `{ before, after }` pairs for the fields that actually
 * moved. `updated_at` and `created_at` are excluded server-side, since recording that
 * a timestamp moved alongside the field that changed doubles every entry for no
 * information.
 */
export type AuditEntry = components['schemas']['AuditEntryResponse']

type AuditQuery = ApiQuery<'/api/audit', 'get'>

/** List recorded changes, newest first. */
export async function getAuditEntries(
  query: AuditQuery = {},
  signal?: AbortSignal,
): Promise<AuditEntry[]> {
  const { data } = await apiClient.get<ApiResponse<'/api/audit', 'get'>>('/api/audit', {
    params: query,
    signal,
  })
  return data
}

/** History of one entity, newest first. */
export async function getEntityHistory(
  entityType: string,
  entityId: string,
  limit = 50,
  signal?: AbortSignal,
): Promise<AuditEntry[]> {
  const { data } = await apiClient.get<ApiResponse<'/api/audit/{entity_type}/{entity_id}', 'get'>>(
    `/api/audit/${entityType}/${entityId}`,
    {
      params: { limit },
      signal,
    },
  )
  return data
}
