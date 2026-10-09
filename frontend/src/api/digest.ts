import type { ApiResponse } from './contracts'

import type { components } from './generated/schema'

/**
 * API access for the digest — everything in the plan needing attention.
 */

import apiClient from './client'

/**
 * Which check produced a finding.
 *
 * A runtime array with the type derived from it, not a bare type union: the panel builds its
 * translation keys dynamically (`digest.finding.${kind}.title`), which the dictionary guard
 * cannot see — it only scans literal `t('a.b')` calls. A test iterates this array instead, so
 * a new kind cannot ship without its sentences in both locales.
 */
export const FINDING_KINDS = [
  'qualification_expiring',
  'qualification_expired',
  'commitment_at_risk',
  'dependency_violated',
  'requirement_uncovered',
] as const satisfies Finding['kind'][]

/**
 * How urgently a finding needs attention.
 *
 * Derived on the backend from how soon it bites, never from the kind of problem: an expiry
 * next week outranks a dependency violation next year, because that is the order somebody
 * would actually work in.
 */
export type Severity = Finding['severity']

export type Finding = components['schemas']['FindingResponse']

export type DigestResponse = components['schemas']['DigestResponse']

export async function getDigest(): Promise<DigestResponse> {
  const response = await apiClient.get<ApiResponse<'/api/digest', 'get'>>('/api/digest')
  return response.data
}
