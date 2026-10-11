import { Card, Group, SimpleGrid, Skeleton, Text, ThemeIcon } from '@mantine/core'
import { IconBriefcase, IconBuilding, IconCalendarEvent, IconUsers } from '@tabler/icons-react'
import type { DashboardResponse } from '../../types/dashboard'
import type { ProjectOverviewItem } from '../../api/projectOverview'
import { useTranslation } from '../../i18n'
import { isoWeekNumber } from '../../utils/date'

/** Summarise the already-loaded responses. Missing/failed data is never a zero. */
export function DashboardStats({
  dashboard,
  projects,
  dashboardPending,
  projectsPending,
  projectsFailed,
}: {
  dashboard: DashboardResponse | null
  projects: ProjectOverviewItem[]
  dashboardPending: boolean
  projectsPending: boolean
  projectsFailed: boolean
}) {
  const { t, locale } = useTranslation()
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 })
  const weekDetail = (week: DashboardResponse['personal_utilization'][number] | undefined) =>
    week
      ? t('dashboard.kw', { week: isoWeekNumber(week.week_start) })
      : t('dashboard.metrics.unavailable')
  const utilization = (week: DashboardResponse['personal_utilization'][number] | undefined) =>
    week && week.total_available > 0 ? `${number.format(week.utilization)} %` : '—'
  const personal = dashboard?.personal_utilization[0]
  const infrastructure = dashboard?.infrastructure_utilization[0]
  const metrics = [
    {
      label: t('dashboard.metrics.projects'),
      value: projectsFailed ? '—' : number.format(projects.length),
      detail: t('dashboard.metrics.allProjects'),
      icon: IconBriefcase,
      pending: projectsPending,
    },
    {
      label: t('dashboard.metrics.workPackages'),
      value: projectsFailed
        ? '—'
        : number.format(projects.reduce((sum, p) => sum + p.active_work_package_count, 0)),
      detail: t('dashboard.metrics.inProjects'),
      icon: IconCalendarEvent,
      pending: projectsPending,
    },
    {
      label: t('dashboard.personalUtilization'),
      value: utilization(personal),
      detail: weekDetail(personal),
      icon: IconUsers,
      pending: dashboardPending,
    },
    {
      label: t('dashboard.infraUtilization'),
      value: utilization(infrastructure),
      detail: weekDetail(infrastructure),
      icon: IconBuilding,
      pending: dashboardPending,
    },
  ]
  return (
    <SimpleGrid cols={{ base: 1, xs: 2, lg: 4 }} spacing="md" className="dashboard-stats">
      {metrics.map((metric) => (
        <Card
          key={metric.label}
          withBorder
          className="capado-glass dashboard-stat"
          component="section"
          aria-label={metric.label}
        >
          <Group justify="space-between" wrap="nowrap" align="flex-start">
            <Text size="sm" c="dimmed" fw={500}>
              {metric.label}
            </Text>
            <ThemeIcon size={36} variant="light" radius="md">
              <metric.icon size={19} stroke={1.6} />
            </ThemeIcon>
          </Group>
          {metric.pending ? (
            <Skeleton height={38} width="50%" my="sm" />
          ) : (
            <Text className="dashboard-stat-value" mt="sm">
              {metric.value}
            </Text>
          )}
          <Text size="xs" c="dimmed">
            {!metric.pending && metric.value === '—'
              ? t('dashboard.metrics.unavailable')
              : metric.detail}
          </Text>
        </Card>
      ))}
    </SimpleGrid>
  )
}
