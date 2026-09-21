/**
 * Unified collapsible card for any detected problem (capacity overload or skill mismatch).
 * Receives a `ProblemBucket` that describes either type and renders the appropriate
 * details section, assignments list, and suggestions.
 */

import React, { useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Collapse,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core'
import {
  IconChevronDown,
  IconChevronRight,
  IconRepeat,
  IconSwitchHorizontal,
} from '@tabler/icons-react'
import { notifications } from '@mantine/notifications'
import { DataTable } from '../../components/layout'
import type {
  Assignment,
  Conflict,
  ConflictAssignmentInfo,
  ResourceType,
} from '../../types/assignment'
import type { WorkPackageRequirement } from '../../types/workPackage'
import type { ResourceSuggestion } from '../../types/suggestion'
import { differenceInDays, formatDate, startOfDayUtc } from '../../utils/date'
import { showErrorNotification } from '../../utils/errorHandling'
import { getSuggestions } from '../../api/suggestions'
import { getWorkPackageRequirements } from '../../api/workPackages'
import { updateAssignment } from '../../api/assignments'
import { searchByQualification } from '../../api/skills'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { ConflictSeverityBadge } from './ConflictSeverityBadge'
import { ConflictAssignmentList } from './ConflictAssignmentList'
import { ConflictSuggestions } from './ConflictSuggestions'
import { resourceTypeLabel } from './bucketing'

// --- Types ---

type ProblemType = 'capacity' | 'skill'

export interface ProblemBucket {
  type: ProblemType
  resource_id: string
  resource_name: string
  resource_type: ResourceType
  /** Assignments involved (for both types). */
  assignments: ConflictAssignmentInfo[]
  /** Capacity-specific: conflict records with phases. */
  conflicts?: Conflict[]
  /** Skill-specific: raw Assignment objects (needed for WP lookup). */
  rawAssignments?: Assignment[]
}

interface Props {
  bucket: ProblemBucket
  onChanged: () => void
}

// --- Helpers ---

function buildWeekdayPattern(conflicts: Conflict[]) {
  if (conflicts.length < 5) return null
  const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
  const days = conflicts.map((c) => startOfDayUtc(c.start_date).getUTCDay())
  const allSameDay = days.every((d) => d === days[0])
  const allSingleDay = conflicts.every((c) => c.start_date === c.end_date)
  if (!allSameDay || !allSingleDay) return null
  return {
    weekday: WEEKDAYS[days[0]],
    count: conflicts.length,
    from: conflicts[0].start_date,
    to: conflicts[conflicts.length - 1].end_date,
  }
}

// --- Component ---

export const ProblemCard = React.memo(function ProblemCard({ bucket, onChanged }: Props) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)

  // Skill mismatch state

  const isCapacity = bucket.type === 'capacity'
  const conflicts = useMemo(() => bucket.conflicts ?? [], [bucket.conflicts])

  // Capacity-specific derived values
  const weekdayPattern = useMemo(() => buildWeekdayPattern(conflicts), [conflicts])
  const earliestStart = conflicts.reduce(
    (acc, c) => (acc === null || c.start_date < acc ? c.start_date : acc),
    null as string | null,
  )
  const latestEnd = conflicts.reduce(
    (acc, c) => (acc === null || c.end_date > acc ? c.end_date : acc),
    null as string | null,
  )
  const totalDays = useMemo(() => {
    let count = 0
    for (const c of conflicts) {
      count += Math.max(1, differenceInDays(c.end_date, c.start_date) + 1)
    }
    return count
  }, [conflicts])
  const worstRatio = useMemo(() => {
    const ratios = conflicts.map((c) => c.overload_ratio).filter((r) => r !== null) as number[]
    return ratios.length > 0 ? Math.max(...ratios) : null
  }, [conflicts])

  // Skill mismatch: load WP requirements + suggestions when expanded
  const firstRawAssignment = bucket.rawAssignments?.[0]
  const firstRawAssignmentId = firstRawAssignment?.id

  /**
   * ONE QUERY FOR THREE REQUESTS, because it is one answer.
   *
   * A swap candidate must satisfy all three parts at once: the work package's requirements, a
   * qualification matching each of them, and availability in the window. Caching the parts separately
   * would let a stale qualification survive a changed requirement and produce a candidate who cannot
   * do the work — so they share a key and go stale together.
   *
   * `enabled` carries what the old effect's early returns did: not a capacity conflict, card open, an
   * assignment present, and dates on it. Expressed as a condition rather than as returns inside an
   * effect, which also means reopening the card reuses the answer instead of recomputing it.
   */
  const startDate = firstRawAssignment?.start_date ?? firstRawAssignment?.start_at?.slice(0, 10)
  const endDate = firstRawAssignment?.end_date ?? firstRawAssignment?.end_at?.slice(0, 10)

  const candidatesQuery = useQuery({
    queryKey: queryKeys.conflicts.swapCandidates(
      firstRawAssignmentId ?? 'none',
      bucket.resource_id,
    ),
    queryFn: async () => {
      const assignment = firstRawAssignment!
      const [requirements, availData] = await Promise.all([
        getWorkPackageRequirements(assignment.work_package_id),
        getSuggestions({
          start_date: startDate!,
          end_date: endDate!,
          allocation_percent: assignment.allocation_percent ?? 100,
        }),
      ])

      const qualificationResults = await Promise.all(
        requirements.map((req) =>
          searchByQualification({
            skill_id: req.skill_id,
            skill_attribute_id: req.skill_attribute_id ?? undefined,
          }),
        ),
      )
      const qualifiedIds = new Set<string>()
      for (const qualified of qualificationResults) {
        for (const r of qualified) qualifiedIds.add(r.id)
      }

      return {
        missingSkills: requirements,
        suggestions: availData.filter(
          (s) => s.resource_id !== bucket.resource_id && qualifiedIds.has(s.resource_id),
        ),
      }
    },
    enabled: !isCapacity && open && Boolean(firstRawAssignmentId) && Boolean(startDate && endDate),
  })

  const missingSkills: WorkPackageRequirement[] = candidatesQuery.data?.missingSkills ?? []
  const suggestions: ResourceSuggestion[] = candidatesQuery.data?.suggestions ?? []
  const loadingSuggestions = candidatesQuery.isPending && candidatesQuery.fetchStatus === 'fetching'

  /**
   * A SWAP WRITES AN ASSIGNMENT: it moves the work to somebody else.
   *
   * Same five keys as the assignments panel, for the same reasons. `onChanged()` is still called
   * because the parent uses it to collapse the card — presentation, not data. Previously it was the
   * ONLY thing that happened, so what got refreshed depended on which screen this card was inside.
   */
  const swapMutation = useMutation({
    mutationFn: (targetResourceId: string) =>
      updateAssignment(firstRawAssignment!.id, { resource_id: targetResourceId }),
    onSuccess: async () => {
      notifications.show({
        title: t('common.saved'),
        message: t('conflicts.swapDone'),
        color: 'green',
      })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.assignments.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.planning.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
        // The Gantt perspectives DRAW the dates and bars this write moves. Adding it here rather than
        // leaving each screen to remember is the same argument as the rest of this layer.
        queryClient.invalidateQueries({ queryKey: queryKeys.gantt.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.resources.all }),
      ])
      onChanged()
    },
    onError: (err) => showErrorNotification(err, t('common.error'), t('conflicts.swapFailed')),
  })

  const swapping = swapMutation.isPending ? (swapMutation.variables ?? null) : null

  const handleApplySwap = (targetResourceId: string) => {
    if (!firstRawAssignment) return
    swapMutation.mutate(targetResourceId)
  }

  // --- Badge & summary ---
  const badgeColor = isCapacity ? 'red' : 'orange'
  const badgeLabel = isCapacity ? t('conflicts.typeCapacity') : t('conflicts.typeSkill')

  const summary = isCapacity
    ? `${resourceTypeLabel(bucket.resource_type)} · ${conflicts.length} ${
        conflicts.length === 1 ? t('conflicts.conflictPhases') : t('conflicts.conflictPhasesPlural')
      } · ${totalDays} ${t('conflicts.days')} · ${bucket.assignments.length} ${
        bucket.assignments.length === 1
          ? t('conflicts.assignment')
          : t('conflicts.assignmentPlural')
      }`
    : `${bucket.assignments.length} ${
        bucket.assignments.length === 1
          ? t('conflicts.assignment')
          : t('conflicts.assignmentPlural')
      }`

  return (
    <Box
      style={{
        border: '1px solid light-dark(var(--mantine-color-gray-3), var(--mantine-color-dark-4))',
        borderRadius: 6,
        backgroundColor: open
          ? 'light-dark(var(--mantine-color-gray-0), var(--mantine-color-dark-6))'
          : undefined,
      }}
    >
      <UnstyledButton onClick={() => setOpen((s) => !s)} style={{ width: '100%', padding: 12 }}>
        <Group justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            {open ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
            <Badge color={badgeColor} variant="light" size="sm">
              {badgeLabel}
            </Badge>
            <Stack gap={0}>
              <Text fw={600}>{bucket.resource_name}</Text>
              <Text size="xs" c="dimmed">
                {summary}
              </Text>
            </Stack>
          </Group>
          {isCapacity && (
            <Group gap="sm">
              {worstRatio !== null && (
                <Badge color="gray" variant="light">
                  {t('conflicts.maxFactor')} {worstRatio.toFixed(2)}×
                </Badge>
              )}
              <Text size="xs" c="dimmed">
                {formatDate(earliestStart)} – {formatDate(latestEnd)}
              </Text>
            </Group>
          )}
        </Group>
      </UnstyledButton>

      <Collapse expanded={open}>
        <Box p="md" pt={0}>
          <Stack gap="md">
            {/* Details section — type-specific */}
            <Box>
              <Text fw={600} size="sm" mb={4}>
                {isCapacity ? t('conflicts.phases') : t('conflicts.missingSkills')}
              </Text>

              {isCapacity ? (
                <>
                  {weekdayPattern ? (
                    <Alert icon={<IconRepeat size={16} />} color="orange" variant="light">
                      <Text size="sm">
                        {t('conflicts.weekdayPattern', {
                          weekday: weekdayPattern.weekday,
                          count: weekdayPattern.count,
                          from: formatDate(weekdayPattern.from),
                          to: formatDate(weekdayPattern.to),
                        })}
                      </Text>
                    </Alert>
                  ) : (
                    <Table withTableBorder fz="xs" layout="fixed">
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th style={{ width: '40%' }}>{t('conflicts.period')}</Table.Th>
                          <Table.Th style={{ width: '20%' }}>{t('conflicts.severity')}</Table.Th>
                          <Table.Th style={{ width: '25%' }}>
                            {t('conflicts.assignedAvailable')}
                          </Table.Th>
                          <Table.Th style={{ width: '15%' }}>{t('conflicts.factor')}</Table.Th>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {conflicts
                          .slice()
                          .sort((a, b) => a.start_date.localeCompare(b.start_date))
                          .map((c) => (
                            <Table.Tr key={c.id}>
                              <Table.Td>
                                {formatDate(c.start_date)} – {formatDate(c.end_date)}
                              </Table.Td>
                              <Table.Td>
                                <ConflictSeverityBadge severity={c.severity} />
                              </Table.Td>
                              <Table.Td>
                                {c.total_assigned_percent.toFixed(0)}% /{' '}
                                {c.available_percent.toFixed(0)}%
                              </Table.Td>
                              <Table.Td>
                                {c.overload_ratio !== null
                                  ? `${c.overload_ratio.toFixed(2)}×`
                                  : '—'}
                              </Table.Td>
                            </Table.Tr>
                          ))}
                      </Table.Tbody>
                    </Table>
                  )}
                </>
              ) : (
                <>
                  {missingSkills.length > 0 ? (
                    <Table withTableBorder fz="xs" layout="fixed">
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th style={{ width: '50%' }}>{t('requirements.skill')}</Table.Th>
                          <Table.Th style={{ width: '30%' }}>
                            {t('requirements.attribute')}
                          </Table.Th>
                          <Table.Th style={{ width: '20%' }}>{t('requirements.quantity')}</Table.Th>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {missingSkills.map((req) => (
                          <Table.Tr key={req.id}>
                            <Table.Td>{req.skill_name}</Table.Td>
                            <Table.Td>{req.skill_attribute_name || '—'}</Table.Td>
                            <Table.Td>{req.quantity}</Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  ) : (
                    <Text size="sm" c="dimmed">
                      {t('suggestionList.loading')}
                    </Text>
                  )}
                </>
              )}
            </Box>

            {/* Assignments with resolution actions */}
            <Box>
              <Text fw={600} size="sm" mb={4}>
                {t('conflicts.assignments')}
              </Text>
              <ConflictAssignmentList assignments={bucket.assignments} onChanged={onChanged} />

              {/* Suggestions */}
              {isCapacity && conflicts.length > 0 && (
                <ConflictSuggestions conflictId={conflicts[0].id} onApplied={onChanged} />
              )}

              {!isCapacity && (
                <Box mt="sm">
                  {loadingSuggestions ? (
                    <Group justify="center" py="sm">
                      <Loader size="sm" />
                      <Text size="sm" c="dimmed">
                        {t('suggestionList.loading')}
                      </Text>
                    </Group>
                  ) : suggestions.length > 0 ? (
                    <>
                      <Text fw={500} size="xs" c="dimmed" mb={4}>
                        {t('conflicts.alternativeResources')}
                      </Text>
                      <DataTable
                        head={
                          <Table.Tr>
                            <Table.Th>{t('suggestionList.name')}</Table.Th>
                            <Table.Th>{t('suggestionList.qualification')}</Table.Th>
                            <Table.Th>{t('suggestionList.freeCapacity')}</Table.Th>
                            <Table.Th style={{ width: 80 }}>{t('common.actions')}</Table.Th>
                          </Table.Tr>
                        }
                      >
                        {suggestions.slice(0, 5).map((s) => (
                          <Table.Tr key={s.resource_id}>
                            <Table.Td>
                              <Text size="xs">{s.resource_name}</Text>
                              <Text size="xs" c="dimmed">
                                {s.department}
                              </Text>
                            </Table.Td>
                            <Table.Td>
                              <Text size="xs">{s.qualification_summary || '—'}</Text>
                            </Table.Td>
                            <Table.Td>
                              <Text size="xs">
                                {t('suggestionList.freePercent', {
                                  value: s.average_free_capacity.toFixed(0),
                                })}
                              </Text>
                            </Table.Td>
                            <Table.Td>
                              <Tooltip label={t('conflicts.applySwap')} withArrow>
                                <ActionIcon
                                  size="sm"
                                  variant="light"
                                  color="teal"
                                  loading={swapping === s.resource_id}
                                  onClick={() => handleApplySwap(s.resource_id)}
                                  aria-label={t('conflicts.applySwap')}
                                >
                                  <IconSwitchHorizontal size={14} />
                                </ActionIcon>
                              </Tooltip>
                            </Table.Td>
                          </Table.Tr>
                        ))}
                      </DataTable>
                    </>
                  ) : null}
                </Box>
              )}
            </Box>
          </Stack>
        </Box>
      </Collapse>
    </Box>
  )
})
