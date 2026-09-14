/**
 * Evidence that the retention settings above actually took effect.
 *
 * Placed next to the retention fields deliberately. Before the scheduler existed, audit
 * retention was set to 24 months on the live instance and nothing had ever deleted a row: the
 * setting was a claim. A number and its evidence belong on the same screen, otherwise the next
 * person has to trust the number the same way.
 *
 * Shows failures and unresolved `running` rows rather than filtering to successes. Those are the
 * two states worth seeing — a job failing nightly, and a job killed mid-run.
 */

import { useQuery } from '@tanstack/react-query'
import { Alert, Badge, Group, Stack, Table, Text } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { getMaintenanceRuns, type JobRunStatus } from '../../api/maintenance'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'

const STATUS_COLOR: Record<JobRunStatus, string> = {
  succeeded: 'green',
  failed: 'red',
  // Amber rather than grey: a row still 'running' long after its start is a killed container,
  // not a job politely in progress.
  running: 'yellow',
  skipped: 'gray',
}

function formatMoment(iso: string): string {
  return new Date(iso).toLocaleString()
}

export function MaintenanceRuns() {
  const { t } = useTranslation()

  const runsQuery = useQuery({
    queryKey: queryKeys.maintenance.runs(10),
    queryFn: () => getMaintenanceRuns(10),
    // A 403 for a non-admin is the expected answer here, not a transient failure, so retrying it
    // would just make the same forbidden request again. The client's default single retry is off.
    retry: false,
  })
  const runs = runsQuery.data ?? null
  // Non-admins get a 403, which is expected rather than an error worth a notification: the rest of
  // the settings page is theirs to use.
  const failed = Boolean(runsQuery.error)

  if (failed || runs === null) return null

  if (runs.length === 0) {
    return (
      <Alert
        icon={<IconAlertTriangle size={16} />}
        color="yellow"
        variant="light"
        title={t('maintenance.neverRan')}
      >
        {t('maintenance.neverRanDetail')}
      </Alert>
    )
  }

  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        {t('maintenance.title')}
      </Text>
      <Table striped withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('maintenance.job')}</Table.Th>
            <Table.Th>{t('maintenance.started')}</Table.Th>
            <Table.Th>{t('maintenance.status')}</Table.Th>
            <Table.Th>{t('maintenance.detail')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {runs.map((run, index) => (
            <Table.Tr key={`${run.job_name}-${run.started_at}-${index}`}>
              <Table.Td>
                <Text size="xs">{run.job_name}</Text>
              </Table.Td>
              <Table.Td>
                <Text size="xs">{formatMoment(run.started_at)}</Text>
              </Table.Td>
              <Table.Td>
                <Group gap={4} wrap="nowrap">
                  <Badge color={STATUS_COLOR[run.status]} size="sm" variant="light">
                    {t(`maintenance.statusValue.${run.status}`)}
                  </Badge>
                </Group>
              </Table.Td>
              <Table.Td>
                <Text size="xs" c="dimmed">
                  {run.detail || '–'}
                </Text>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  )
}
