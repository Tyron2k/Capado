/**
 * Report downloads on the dashboard.
 *
 * Placed here rather than on its own page because a manager lands on the dashboard, and a report
 * one navigation step away from where the numbers are shown is a report people ask a planner to
 * email them instead.
 *
 * The week range is optional and empty by default: the server picks the current week plus twelve,
 * which is a useful sheet without anybody configuring anything. A required range would make the
 * common case slower than it needs to be.
 */

import { useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { Accordion, Button, Card, Group, Select, Stack, Text } from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { IconFileSpreadsheet } from '@tabler/icons-react'
import { downloadProjectReport, downloadUtilizationReport } from '../../api/reports'
import { getGroups } from '../../api/resources'
import { showErrorNotification } from '../../utils/errorHandling'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'

export function ReportCard() {
  const { t } = useTranslation()
  const [start, setStart] = useState<string | null>(null)
  const [end, setEnd] = useState<string | null>(null)
  const [groupId, setGroupId] = useState<string | null>(null)
  const [busy, setBusy] = useState<'utilization' | 'projects' | null>(null)

  /**
   * The group filter, sharing `resources.groups('personal')` with every other group picker.
   *
   * Optional by design and still silent on failure: without it the report covers everybody, which is
   * the more common question anyway. A notification for a degraded filter would be noise.
   */
  const groupsQuery = useQuery({
    queryKey: queryKeys.resources.groups('personal'),
    queryFn: () => getGroups('personal'),
  })
  const groups = useMemo(
    () => (groupsQuery.data ?? []).map((group) => ({ value: group.id, label: group.name })),
    [groupsQuery.data],
  )

  const run = async (which: 'utilization' | 'projects') => {
    setBusy(which)
    try {
      if (which === 'utilization') {
        await downloadUtilizationReport(start ?? undefined, end ?? undefined, groupId ?? undefined)
      } else {
        await downloadProjectReport()
      }
    } catch (error: unknown) {
      showErrorNotification(error, t('common.error'), t('reports.failed'))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card withBorder padding={0} className="dashboard-reports">
      <Accordion>
        <Accordion.Item value="reports">
          <Accordion.Control icon={<IconFileSpreadsheet size={20} />}>
            <Text fw={600}>{t('reports.title')}</Text>
            <Text size="sm" c="dimmed">
              {t('reports.projectsHint')}
            </Text>
          </Accordion.Control>
          <Accordion.Panel>
            <Stack gap="sm">
              <Group gap="sm" align="flex-end" wrap="wrap" className="dashboard-report-filters">
                <DateInput
                  label={t('reports.from')}
                  placeholder={t('reports.currentWeek')}
                  value={start}
                  onChange={(value) => setStart(value || null)}
                  clearable
                  size="sm"
                  valueFormat="DD.MM.YYYY"
                />
                <DateInput
                  label={t('reports.to')}
                  placeholder={t('reports.twelveWeeks')}
                  value={end}
                  onChange={(value) => setEnd(value || null)}
                  clearable
                  size="sm"
                  valueFormat="DD.MM.YYYY"
                />
                {groups.length > 0 && (
                  <Select
                    label={t('reports.group')}
                    placeholder={t('reports.allGroups')}
                    data={groups}
                    value={groupId}
                    onChange={setGroupId}
                    clearable
                    size="sm"
                  />
                )}
                <Button
                  leftSection={<IconFileSpreadsheet size={16} />}
                  size="sm"
                  loading={busy === 'utilization'}
                  onClick={() => void run('utilization')}
                >
                  {t('reports.utilization')}
                </Button>
              </Group>
              <Group gap="xs">
                <Button
                  leftSection={<IconFileSpreadsheet size={16} />}
                  size="sm"
                  variant="default"
                  loading={busy === 'projects'}
                  onClick={() => void run('projects')}
                >
                  {t('reports.projects')}
                </Button>
                <Text size="sm" c="dimmed">
                  {t('reports.projectsHint')}
                </Text>
              </Group>
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Card>
  )
}
