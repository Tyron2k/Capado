/**
 * List of assignments involved in a conflict, grouped by project.
 * Each row has resolution actions (popover).
 */

import { useMemo } from 'react'
import { Anchor, Box, Group, Stack, Table, Text, Tooltip } from '@mantine/core'
import { useNavigate } from 'react-router-dom'
import { IconAlertTriangle } from '@tabler/icons-react'
import type { ConflictAssignmentInfo } from '../../types/assignment'
import { formatDate, formatDateTime } from '../../utils/date'
import { useTranslation } from '../../i18n'
import { usePermissions } from '../../hooks/usePermissions'
import { ConflictResolutionActions } from './ConflictResolutionActions'

interface Props {
  assignments: ConflictAssignmentInfo[]
  onChanged: () => void
  focusedWorkPackageId?: string
}

export function ConflictAssignmentList({ assignments, onChanged, focusedWorkPackageId }: Props) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { canWrite } = usePermissions()
  const grouped = useMemo(() => {
    const map = new Map<string, { project_name: string; items: ConflictAssignmentInfo[] }>()
    for (const a of assignments) {
      const key = a.project_id ?? ''
      const entry = map.get(key) ?? {
        project_name: a.project_name ?? '— no project —',
        items: [],
      }
      entry.items.push(a)
      map.set(key, entry)
    }
    return Array.from(map.entries()).sort(([, x], [, y]) =>
      x.project_name.localeCompare(y.project_name, 'de'),
    )
  }, [assignments])

  if (assignments.length === 0) {
    return <Text c="dimmed">{t('conflicts.noAssignmentsRemaining')}</Text>
  }

  return (
    <Stack gap="sm">
      {grouped.map(([projectKey, group]) => (
        <Box
          key={projectKey || '__no_project__'}
          style={{
            borderLeft: '3px solid var(--mantine-color-blue-4)',
            paddingLeft: 12,
          }}
        >
          <Group justify="space-between" mb={4}>
            <Text fw={600} size="sm">
              {group.project_name}
            </Text>
            {projectKey && (
              <Anchor
                size="xs"
                onClick={() => navigate(`/gantt?project=${projectKey}`)}
                style={{ cursor: 'pointer' }}
              >
                {t('conflicts.openInGantt')}
              </Anchor>
            )}
          </Group>
          <Table withTableBorder striped fz="xs" layout="fixed">
            <Table.Thead>
              <Table.Tr>
                <Table.Th style={{ width: '35%' }}>{t('conflicts.workPackage')}</Table.Th>
                <Table.Th style={{ width: '35%' }}>{t('conflicts.period')}</Table.Th>
                <Table.Th style={{ width: '20%' }}>{t('conflicts.allocation')}</Table.Th>
                {canWrite && <Table.Th style={{ width: '10%' }} aria-label={t('common.actions')} />}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {group.items.map((a) => {
                const wasRemoved = !a.work_package_name && !a.start_date && !a.start_at
                if (wasRemoved) {
                  return (
                    <Table.Tr key={a.assignment_id}>
                      <Table.Td colSpan={canWrite ? 4 : 3}>
                        <Text c="dimmed">{t('conflicts.assignmentRemoved')}</Text>
                      </Table.Td>
                    </Table.Tr>
                  )
                }
                const period =
                  a.start_at && a.end_at
                    ? `${formatDateTime(a.start_at)} – ${formatDateTime(a.end_at)}`
                    : `${formatDate(a.start_date)} – ${formatDate(a.end_date)}`
                return (
                  <Table.Tr
                    key={a.assignment_id}
                    data-focused={a.work_package_id === focusedWorkPackageId ? 'true' : undefined}
                    style={
                      a.work_package_id === focusedWorkPackageId
                        ? { backgroundColor: 'var(--mantine-color-yellow-light)' }
                        : undefined
                    }
                  >
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        {a.work_package_name ?? '—'}
                        {a.skill_mismatch && (
                          <Tooltip label={t('planning.skillMismatch')} withArrow>
                            <IconAlertTriangle
                              size={12}
                              color="var(--mantine-color-orange-6)"
                              aria-label={t('planning.skillMismatch')}
                            />
                          </Tooltip>
                        )}
                      </Group>
                    </Table.Td>
                    <Table.Td>{period}</Table.Td>
                    <Table.Td>
                      {a.allocation_percent != null ? `${a.allocation_percent}%` : '—'}
                    </Table.Td>
                    {canWrite && (
                      <Table.Td>
                        <ConflictResolutionActions assignment={a} onChanged={onChanged} />
                      </Table.Td>
                    )}
                  </Table.Tr>
                )
              })}
            </Table.Tbody>
          </Table>
        </Box>
      ))}
    </Stack>
  )
}
