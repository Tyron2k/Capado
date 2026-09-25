/**
 * Inline conflicts section for the planning overview tab.
 * Shows all problems (capacity overloads + skill mismatches) using
 * the unified ProblemCard component.
 *
 * Receives pre-fetched data from PlanningOverviewPanel to avoid
 * redundant API requests.
 */
import { useEffect, useMemo, useRef } from 'react'
import { Button, Group, Stack, Text } from '@mantine/core'
import type { Assignment, Conflict, ConflictAssignmentInfo } from '../../types/assignment'
import { useTranslation } from '../../i18n'
import { SectionHeader } from '../../components/layout'
import { buildResourceBuckets, SEVERITY_ORDER } from '../conflicts/bucketing'
import { ProblemCard, type ProblemBucket } from '../conflicts/ProblemCard'
import { matchesFocusedConflict, matchesFocusedMismatch, type ConflictFocus } from './conflictFocus'

interface ConflictsSectionProps {
  /** Pre-fetched conflict records. */
  conflicts: Conflict[]
  /** Pre-fetched assignments with skill mismatches. */
  mismatches: Assignment[]
  /** Called when user applies a resolution (swap, dismiss, etc.). */
  onChanged: () => void
  focus?: ConflictFocus | null
  onClearFocus?: () => void
}

/**
 * Renders capacity overloads and skill mismatches as unified ProblemCards.
 * Data is passed in as props (fetched by PlanningOverviewPanel).
 */
export function ConflictsSection({
  conflicts,
  mismatches,
  onChanged,
  focus,
  onClearFocus,
}: ConflictsSectionProps) {
  const { t } = useTranslation()
  const sectionRef = useRef<HTMLDivElement>(null)
  const focusKey = focus
    ? `${focus.projectId ?? ''}:${focus.workPackageId ?? ''}:${focus.resourceId ?? ''}`
    : null
  useEffect(() => {
    if (focusKey) sectionRef.current?.scrollIntoView?.({ block: 'start' })
  }, [focusKey])

  const visibleConflicts = useMemo(
    () =>
      focus ? conflicts.filter((conflict) => matchesFocusedConflict(conflict, focus)) : conflicts,
    [conflicts, focus],
  )
  const visibleMismatches = useMemo(
    () =>
      focus
        ? mismatches.filter((assignment) => matchesFocusedMismatch(assignment, focus))
        : mismatches,
    [mismatches, focus],
  )

  const focusedName = focus?.workPackageId
    ? (visibleConflicts
        .flatMap((conflict) => conflict.assignments)
        .find((assignment) => assignment.work_package_id === focus.workPackageId)
        ?.work_package_name ??
      visibleMismatches.find((assignment) => assignment.work_package_id === focus.workPackageId)
        ?.work_package_name)
    : focus?.projectId
      ? (visibleConflicts
          .flatMap((conflict) => conflict.assignments)
          .find((assignment) => assignment.project_id === focus.projectId)?.project_name ??
        visibleMismatches.find((assignment) => assignment.project_id === focus.projectId)
          ?.project_name)
      : (visibleConflicts[0]?.resource_name ?? visibleMismatches[0]?.resource_name)

  /** Build unified ProblemBucket list from both sources. */
  const problemBuckets = useMemo<ProblemBucket[]>(() => {
    const buckets: ProblemBucket[] = []

    // Capacity problems (grouped by resource via bucketing)
    const capacityBuckets = buildResourceBuckets(visibleConflicts)
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
    for (const a of visibleMismatches) {
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
  }, [visibleConflicts, visibleMismatches])

  const totalProblems = visibleConflicts.length + visibleMismatches.length

  const focusNotice = focus && (
    <Group justify="space-between" gap="sm">
      <Text size="sm">
        {t('planning.conflictsFiltered')}
        {focusedName ? `: ${focusedName}` : ''}
      </Text>
      {onClearFocus && (
        <Button variant="subtle" size="xs" onClick={onClearFocus}>
          {t('planning.showAllConflicts')}
        </Button>
      )}
    </Group>
  )

  if (totalProblems === 0) {
    return (
      <div ref={sectionRef}>
        <SectionHeader title={t('conflicts.title')} />
        {focusNotice}
        <Text c="dimmed" size="sm">
          {t(focus ? 'planning.noMatchingConflicts' : 'conflicts.noConflicts')}
        </Text>
      </div>
    )
  }

  return (
    <div ref={sectionRef}>
      <SectionHeader title={`${t('conflicts.title')} (${totalProblems})`} />
      {focusNotice}
      <Stack gap="xs">
        {problemBuckets.map((b) => (
          <ProblemCard
            key={`${b.type}-${b.resource_id}-${focus?.projectId ?? ''}-${focus?.workPackageId ?? ''}-${focus?.resourceId ?? ''}`}
            bucket={b}
            onChanged={onChanged}
            initiallyOpen={Boolean(focus)}
            focusedWorkPackageId={focus?.workPackageId}
          />
        ))}
      </Stack>
    </div>
  )
}
