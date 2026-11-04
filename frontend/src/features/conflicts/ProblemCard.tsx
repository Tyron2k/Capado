/**
 * Unified collapsible card for any detected problem (capacity overload or skill mismatch).
 * Receives a `ProblemBucket` that describes either type and renders the appropriate
 * details section, assignments list, and suggestions.
 */

import React, { useMemo, useState } from 'react'

import {
  Alert,
  Badge,
  Box,
  Collapse,
  Group,
  Stack,
  Table,
  Text,
  UnstyledButton,
} from '@mantine/core'
import { IconChevronDown, IconChevronRight, IconRepeat } from '@tabler/icons-react'
import type {
  Assignment,
  Conflict,
  ConflictAssignmentInfo,
  ResourceType,
} from '../../types/assignment'
import { differenceInDays, formatDate, startOfDayUtc } from '../../utils/date'
import { useTranslation } from '../../i18n'
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
  initiallyOpen?: boolean
  focusedWorkPackageId?: string
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

export const ProblemCard = React.memo(function ProblemCard({
  bucket,
  onChanged,
  initiallyOpen = false,
  focusedWorkPackageId,
}: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(initiallyOpen)
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
      <UnstyledButton
        onClick={() => setOpen((s) => !s)}
        aria-expanded={open}
        style={{ width: '100%', padding: 12 }}
      >
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
                {isCapacity ? t('conflicts.phases') : t('conflicts.qualificationCheck')}
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
                    <Table.ScrollContainer minWidth={560} type="native">
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
                    </Table.ScrollContainer>
                  )}
                </>
              ) : (
                <Text size="sm" c="dimmed">
                  {t('conflicts.qualificationRule')}
                </Text>
              )}
            </Box>

            {/* Assignments with resolution actions */}
            <Box>
              <Text fw={600} size="sm" mb={4}>
                {t('conflicts.assignments')}
              </Text>
              <ConflictAssignmentList
                assignments={bucket.assignments}
                onChanged={onChanged}
                focusedWorkPackageId={focusedWorkPackageId}
              />

              {open &&
                (isCapacity ? bucket.assignments : (bucket.rawAssignments ?? [])).map((booking) => {
                  const id = 'assignment_id' in booking ? booking.assignment_id : booking.id
                  return (
                    <Box key={id} mt="sm">
                      <Text size="xs" fw={600}>
                        {booking.work_package_name}
                      </Text>
                      <ConflictSuggestions
                        assignmentId={id}
                        alternativesOnly={!isCapacity}
                        onApplied={onChanged}
                      />
                    </Box>
                  )
                })}
            </Box>
          </Stack>
        </Box>
      </Collapse>
    </Box>
  )
})
