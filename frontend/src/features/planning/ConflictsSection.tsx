/**
 * Inline conflicts section for the planning overview tab.
 * Shows all problems (capacity overloads + skill mismatches) using
 * the unified ProblemCard component.
 *
 * Receives pre-fetched data from PlanningOverviewPanel to avoid
 * redundant API requests.
 */
import { useMemo } from 'react'
import { Stack, Text } from '@mantine/core'
import type { Assignment, Conflict, ConflictAssignmentInfo } from '../../types/assignment'
import { useTranslation } from '../../i18n'
import { SectionHeader } from '../../components/layout'
import { buildResourceBuckets, SEVERITY_ORDER } from '../conflicts/bucketing'
import { ProblemCard, type ProblemBucket } from '../conflicts/ProblemCard'

interface ConflictsSectionProps {
  /** Pre-fetched conflict records. */
  conflicts: Conflict[]
  /** Pre-fetched assignments with skill mismatches. */
  mismatches: Assignment[]
  /** Called when user applies a resolution (swap, dismiss, etc.). */
  onChanged: () => void
}

/**
 * Renders capacity overloads and skill mismatches as unified ProblemCards.
 * Data is passed in as props (fetched by PlanningOverviewPanel).
 */
export function ConflictsSection({ conflicts, mismatches, onChanged }: ConflictsSectionProps) {
  const { t } = useTranslation()

  /** Build unified ProblemBucket list from both sources. */
  const problemBuckets = useMemo<ProblemBucket[]>(() => {
    const buckets: ProblemBucket[] = []

    // Capacity problems (grouped by resource via bucketing)
    const capacityBuckets = buildResourceBuckets(conflicts)
    capacityBuckets.sort((a, b) => {
      const s = SEVERITY_ORDER[a.worstSeverity] - SEVERITY_ORDER[b.worstSeverity]
      if (s !== 0) return s
      return a.resource_name.localeCompare(b.resource_name, 'de')
    })
    for (const rb of capacityBuckets) {
      // Deduplicate assignments from all conflict records
      const byKey = new Map<string, ConflictAssignmentInfo>()
      for (const c of rb.conflicts) {
        for (const a of c.assignments) {
          if (!byKey.has(a.assignment_id)) byKey.set(a.assignment_id, a)
        }
      }
      buckets.push({
        type: 'capacity',
        resource_id: rb.resource_id,
        resource_name: rb.resource_name,
        resource_type: rb.resource_type,
        assignments: Array.from(byKey.values()),
        conflicts: rb.conflicts,
      })
    }

    // Skill mismatch problems (grouped by resource)
    const mismatchMap = new Map<string, Assignment[]>()
    for (const a of mismatches) {
      const existing = mismatchMap.get(a.resource_id)
      if (existing) existing.push(a)
      else mismatchMap.set(a.resource_id, [a])
    }
    const sortedMismatches = Array.from(mismatchMap.entries()).sort(([, a], [, b]) =>
      (a[0].resource_name ?? '').localeCompare(b[0].resource_name ?? '', 'de'),
    )
    for (const [resourceId, assignments] of sortedMismatches) {
      const infos: ConflictAssignmentInfo[] = assignments.map((a) => ({
        assignment_id: a.id,
        work_package_id: a.work_package_id,
        work_package_name: a.work_package_name ?? undefined,
        project_id: a.project_id ?? undefined,
        project_name: a.project_name ?? undefined,
        resource_id: a.resource_id,
        resource_name: a.resource_name ?? undefined,
        start_date: a.start_date ?? undefined,
        end_date: a.end_date ?? undefined,
        allocation_percent: a.allocation_percent ?? undefined,
        start_at: a.start_at ?? undefined,
        end_at: a.end_at ?? undefined,
        skill_mismatch: true,
      }))
      buckets.push({
        type: 'skill',
        resource_id: resourceId,
        resource_name: assignments[0].resource_name ?? '—',
        resource_type: assignments[0].resource_type,
        assignments: infos,
        rawAssignments: assignments,
      })
    }

    return buckets
  }, [conflicts, mismatches])

  const totalProblems = conflicts.length + mismatches.length

  if (totalProblems === 0) {
    return (
      <div>
        <SectionHeader title={t('conflicts.title')} />
        <Text c="dimmed" size="sm">
          {t('conflicts.noConflicts')}
        </Text>
      </div>
    )
  }

  return (
    <div>
      <SectionHeader title={`${t('conflicts.title')} (${totalProblems})`} />
      <Stack gap="xs">
        {problemBuckets.map((b) => (
          <ProblemCard key={`${b.type}-${b.resource_id}`} bucket={b} onChanged={onChanged} />
        ))}
      </Stack>
    </div>
  )
}
