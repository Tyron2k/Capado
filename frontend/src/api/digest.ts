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
] as const

type FindingKind = (typeof FINDING_KINDS)[number]

/**
 * How urgently a finding needs attention.
 *
 * Derived on the backend from how soon it bites, never from the kind of problem: an expiry
 * next week outranks a dependency violation next year, because that is the order somebody
 * would actually work in.
 */
export type Severity = 'critical' | 'warning' | 'info'

export interface Finding {
  kind: FindingKind
  severity: Severity
  /**
   * Substitution values for the sentence selected by `kind`.
   *
   * The backend used to send a rendered `title` and `detail` — composed as German prose in
   * Python, which made this locale-switching UI show German sentences under English
   * headings. It now sends the values and this side owns the wording, like every other
   * string in the app. Dates arrive ISO so they can be formatted per locale.
   */
  params: Record<string, string>
  /** The day the problem bites. In the past for something already broken. */
  due: string
  resource_id: string | null
  work_package_id: string | null
  project_id: string | null
}

export interface DigestResponse {
  /**
   * The day the digest was computed against.
   *
   * Severity and horizon are relative to it, so a client showing a cached digest can say
   * how old it is instead of presenting stale urgency as current.
   */
  generated_for: string
  counts: Record<Severity, number>
  findings: Finding[]
  /**
   * Findings that exceeded the configured cap and are NOT in the list.
   *
   * Shown to the user rather than hidden: a truncated digest that looks complete is worse
   * than one that says it is truncated.
   */
  suppressed_count: number
}

export async function getDigest(): Promise<DigestResponse> {
  const response = await apiClient.get<DigestResponse>('/api/digest')
  return response.data
}
