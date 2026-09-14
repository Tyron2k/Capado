/**
 * Dashboard page: Application start page with utilization charts and project KPI table.
 *
 * Combines the former utilization charts (personal + infrastructure per calendar week)
 * with the full project overview table (progress, deadlines, conflicts, utilization).
 */

import { useEffect, useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { DigestPanel } from './DigestPanel'
import { ReportCard } from './ReportCard'
import {
  Alert,
  Badge,
  Tooltip,
  Box,
  Button,
  Center,
  Grid,
  Group,
  Loader,
  Paper,
  Progress,
  Stack,
  Table,
  Text,
  UnstyledButton,
} from '@mantine/core'
import { DataTable, PageLayout, SectionHeader } from '../../components/layout'
import { BarChart } from '@mantine/charts'
import { showErrorNotification } from '../../utils/errorHandling'
import {
  IconAlertCircle,
  IconChartBar,
  IconChevronDown,
  IconChevronUp,
  IconClock,
  IconSelector,
} from '@tabler/icons-react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { getDashboard } from '../../api/dashboard'
import { getProjectOverview } from '../../api/projectOverview'
import type { DashboardResponse, WeeklyUtilizationResponse } from '../../types/dashboard'
import type { ProjectOverviewItem } from '../../api/projectOverview'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { differenceInDays, formatDate, isoWeekNumber, todayUtc } from '../../utils/date'

/** Generate calendar week label from ISO date (e.g. "CW 23"). */
function formatKW(
  weekStart: string,
  kwLabel: (params: Record<string, string | number>) => string,
): string {
  return kwLabel({ week: isoWeekNumber(weekStart) })
}

/** Prepare utilization data for the BarChart with overbooked segment. */
function prepareChartData(
  utilization: WeeklyUtilizationResponse[],
  kwLabel: (params: Record<string, string | number>) => string,
  normalLabel: string,
  overbookedLabel: string,
) {
  return utilization.map((week) => {
    const total = Math.round(week.utilization * 10) / 10
    const overbooked = Math.round(week.overbooked * 10) / 10
    const normal = Math.round((total - overbooked) * 10) / 10
    return {
      kw: formatKW(week.week_start, kwLabel),
      [normalLabel]: Math.max(normal, 0),
      [overbookedLabel]: overbooked,
    }
  })
}

/** Format progress percentage with comma as decimal separator. */
function formatProgress(value: number): string {
  return `${value.toFixed(1).replace('.', ',')} %`
}

/** Color for conflict badge based on count. */
function conflictBadgeColor(count: number): string {
  if (count >= 3) return 'red'
  if (count >= 1) return 'yellow'
  return 'green'
}

/** Deadline urgency status based on proximity. */
function deadlineStatus(iso: string): 'overdue' | 'soon' | 'normal' {
  const diffDays = differenceInDays(iso, todayUtc())
  if (diffDays < 0) return 'overdue'
  if (diffDays <= 14) return 'soon'
  return 'normal'
}

/** Color for deadline text based on urgency status. */
function deadlineColor(iso: string): string {
  const status = deadlineStatus(iso)
  if (status === 'overdue') return 'var(--mantine-color-red-6)'
  if (status === 'soon') return 'var(--mantine-color-yellow-7)'
  return 'inherit'
}

export function DashboardPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const [sortKey, setSortKey] = useState<string>('start_date')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  /**
   * THE DASHBOARD IS THE MOST DOWNSTREAM SCREEN IN THE PRODUCT, and until now the most reliably wrong.
   *
   * Its figures and its project overview are computed from the entire plan. Nothing on this page is
   * editable, so nothing on this page ever refreshed it: it was loaded once on mount and then showed
   * whatever was true at that moment for as long as the tab stayed open. A planner who moved a date on
   * another screen and came back here read stale utilisation and a stale conflict count — the numbers
   * they would base the next decision on.
   *
   * Both queries live under `dashboard`, which every plan-changing mutation now invalidates. The
   * `digest` key beside it is the findings LIST; these are the figures around it. Same lifetime,
   * different endpoints, so different keys.
   *
   * The project overview shares `dashboard.projectOverview()` with the Gantt section's conflict badges,
   * which asks the same question of the same endpoint.
   */
  const dashboardQuery = useQuery({
    queryKey: queryKeys.dashboard.summary(),
    queryFn: () => getDashboard(),
  })
  const dashboardData: DashboardResponse | null = dashboardQuery.data ?? null
  const chartsLoading = dashboardQuery.isPending

  useEffect(() => {
    if (dashboardQuery.error) {
      showErrorNotification(dashboardQuery.error, t('common.error'), t('dashboard.loadFailed'))
    }
  }, [dashboardQuery.error, t])

  const overviewQuery = useQuery({
    queryKey: queryKeys.dashboard.projectOverview(),
    queryFn: () => getProjectOverview(),
  })
  const projects: ProjectOverviewItem[] = overviewQuery.data?.projects ?? []
  const projectsLoading = overviewQuery.isPending

  /**
   * Reported INLINE, in the table's own place, rather than as a notification — the charts above it are
   * still valid, so a page-level error message would overstate what failed. The backend's `detail` is
   * preferred over the generic string because it names the reason.
   */
  const projectsError = overviewQuery.error
    ? axios.isAxiosError(overviewQuery.error)
      ? (overviewQuery.error.response?.data?.detail ?? t('projectOverview.loadFailed'))
      : t('projectOverview.loadFailed')
    : null

  // --- Sorting for project table ---

  const sorted = useMemo(() => {
    return [...projects].sort((a, b) => {
      let result: number
      switch (sortKey) {
        case 'name':
          result = a.project_name.localeCompare(b.project_name, 'de')
          break
        case 'start_date':
          result = a.start_date.localeCompare(b.start_date)
          break
        case 'progress':
          result = a.progress_percent - b.progress_percent
          break
        case 'conflicts':
          result = a.open_conflict_count - b.open_conflict_count
          break
        case 'deadline':
          result = a.next_deadline.localeCompare(b.next_deadline)
          break
        default:
          return 0
      }
      return sortDir === 'asc' ? result : -result
    })
  }, [projects, sortKey, sortDir])

  const toggleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const getSortIcon = (column: string) => {
    if (sortKey !== column) return <IconSelector size={14} style={{ opacity: 0.4 }} />
    return sortDir === 'asc' ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />
  }

  // --- Chart data ---

  const utilizationLabel = t('dashboard.utilization')
  const overbookedLabel = t('dashboard.overbooked')
  const kwLabel = (params: Record<string, string | number>) => t('dashboard.kw', params)
  const personalChartData = dashboardData
    ? prepareChartData(
        dashboardData.personal_utilization,
        kwLabel,
        utilizationLabel,
        overbookedLabel,
      )
    : []
  const infraChartData = dashboardData
    ? prepareChartData(
        dashboardData.infrastructure_utilization,
        kwLabel,
        utilizationLabel,
        overbookedLabel,
      )
    : []

  return (
    <PageLayout title={t('dashboard.title')}>
      {/* What needs attention, before the charts: the charts describe the plan, this says
          what to do about it. */}
      <DigestPanel />

      {/* Exports below the digest: the digest says what to act on, the reports are what you
          take to a meeting about it. */}
      <ReportCard />

      {/* Utilization Charts */}
      {chartsLoading ? (
        <Center py="xl">
          <Loader />
        </Center>
      ) : (
        dashboardData && (
          <Grid mb="md">
            <Grid.Col span={{ base: 12, md: 6 }} style={{ minWidth: 0 }}>
              <Paper p="md" withBorder>
                <Group justify="space-between" mb="sm">
                  <Text fw={600} size="lg">
                    {t('dashboard.personalUtilization')}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {t('dashboard.perCalendarWeek')}
                  </Text>
                </Group>
                {personalChartData.length === 0 ? (
                  <Text c="dimmed" ta="center" py="md">
                    {t('dashboard.noUtilizationData')}
                  </Text>
                ) : (
                  <BarChart
                    h={250}
                    data={personalChartData}
                    dataKey="kw"
                    type="stacked"
                    series={[
                      { name: overbookedLabel, color: 'red.6' },
                      { name: utilizationLabel, color: 'teal.6' },
                    ]}
                    tickLine="y"
                    yAxisProps={{ domain: [0, 'auto'] }}
                    valueFormatter={(value) => `${value}%`}
                    barProps={{ radius: [4, 4, 0, 0] }}
                  />
                )}
              </Paper>
            </Grid.Col>

            <Grid.Col span={{ base: 12, md: 6 }} style={{ minWidth: 0 }}>
              <Paper p="md" withBorder>
                <Group justify="space-between" mb="sm">
                  <Text fw={600} size="lg">
                    {t('dashboard.infraUtilization')}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {t('dashboard.perCalendarWeek')}
                  </Text>
                </Group>
                {infraChartData.length === 0 ? (
                  <Text c="dimmed" ta="center" py="md">
                    {t('dashboard.noUtilizationData')}
                  </Text>
                ) : (
                  <BarChart
                    h={250}
                    data={infraChartData}
                    dataKey="kw"
                    type="stacked"
                    series={[
                      { name: overbookedLabel, color: 'red.6' },
                      { name: utilizationLabel, color: 'teal.6' },
                    ]}
                    tickLine="y"
                    yAxisProps={{ domain: [0, 'auto'] }}
                    valueFormatter={(value) => `${value}%`}
                    barProps={{ radius: [4, 4, 0, 0] }}
                  />
                )}
              </Paper>
            </Grid.Col>
          </Grid>
        )
      )}

      {/* Project Overview Table */}
      <SectionHeader title={t('projectOverview.title')} />

      {projectsError && (
        <Alert icon={<IconAlertCircle size={16} />} color="red" mb="md">
          {projectsError}
        </Alert>
      )}

      {!projectsError && (
        <DataTable
          loading={projectsLoading}
          empty={projects.length === 0}
          emptyMessage={t('projectOverview.noProjects')}
          testId="project-overview-table"
          head={
            <Table.Tr>
              <Table.Th>
                <UnstyledButton onClick={() => toggleSort('name')}>
                  <Group gap={4}>
                    {t('projectOverview.name')} {getSortIcon('name')}
                  </Group>
                </UnstyledButton>
              </Table.Th>
              <Table.Th>
                <UnstyledButton onClick={() => toggleSort('start_date')}>
                  <Group gap={4}>
                    {t('projectOverview.period')} {getSortIcon('start_date')}
                  </Group>
                </UnstyledButton>
              </Table.Th>
              <Table.Th>
                <UnstyledButton onClick={() => toggleSort('progress')}>
                  <Group gap={4}>
                    {t('projectOverview.progress')} {getSortIcon('progress')}
                  </Group>
                </UnstyledButton>
              </Table.Th>
              <Table.Th>{t('projectOverview.activeWP')}</Table.Th>
              <Table.Th>{t('projectOverview.utilization')}</Table.Th>
              <Table.Th>
                <UnstyledButton onClick={() => toggleSort('deadline')}>
                  <Group gap={4}>
                    {t('projectOverview.nextDeadline')} {getSortIcon('deadline')}
                  </Group>
                </UnstyledButton>
              </Table.Th>
              <Table.Th>
                <UnstyledButton onClick={() => toggleSort('conflicts')}>
                  <Group gap={4}>
                    {t('projectOverview.conflicts')} {getSortIcon('conflicts')}
                  </Group>
                </UnstyledButton>
              </Table.Th>
              <Table.Th>{t('projectOverview.lateness')}</Table.Th>
              <Table.Th>{t('projectOverview.dependencies')}</Table.Th>
              <Table.Th>{t('projectOverview.float')}</Table.Th>
              <Table.Th>{t('projectOverview.actions')}</Table.Th>
            </Table.Tr>
          }
        >
          {sorted.map((p) => (
            <Table.Tr key={p.project_id} data-testid={`project-overview-row-${p.project_id}`}>
              <Table.Td>{p.project_name}</Table.Td>
              <Table.Td>
                {formatDate(p.start_date)} – {formatDate(p.end_date)}
              </Table.Td>
              <Table.Td>
                <Stack gap={2}>
                  <Text size="sm">{formatProgress(p.progress_percent)}</Text>
                  <Progress value={p.progress_percent} size="xs" />
                </Stack>
              </Table.Td>
              <Table.Td>{p.active_work_package_count}</Table.Td>
              <Table.Td>
                {p.average_resource_utilization_percent !== null
                  ? `${p.average_resource_utilization_percent.toFixed(1)} %`
                  : '—'}
              </Table.Td>
              <Table.Td>
                <Group gap={4} wrap="nowrap">
                  {deadlineStatus(p.next_deadline) === 'overdue' && (
                    <IconAlertCircle
                      size={14}
                      color="var(--mantine-color-red-6)"
                      aria-hidden="true"
                    />
                  )}
                  {deadlineStatus(p.next_deadline) === 'soon' && (
                    <IconClock size={14} color="var(--mantine-color-yellow-7)" aria-hidden="true" />
                  )}
                  <Box style={{ color: deadlineColor(p.next_deadline) }}>
                    {formatDate(p.next_deadline)}
                  </Box>
                </Group>
              </Table.Td>
              <Table.Td>
                <Badge
                  color={conflictBadgeColor(p.open_conflict_count)}
                  variant="filled"
                  style={{
                    cursor: p.open_conflict_count > 0 ? 'pointer' : 'default',
                  }}
                  onClick={
                    p.open_conflict_count > 0
                      ? () => navigate(`/planning?project=${p.project_id}`)
                      : undefined
                  }
                  onKeyDown={
                    p.open_conflict_count > 0
                      ? (e: React.KeyboardEvent) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            navigate(`/planning?project=${p.project_id}`)
                          }
                        }
                      : undefined
                  }
                  tabIndex={p.open_conflict_count > 0 ? 0 : undefined}
                  role={p.open_conflict_count > 0 ? 'button' : undefined}
                  aria-label={
                    p.open_conflict_count > 0 ? t('projectOverview.toProjectConflicts') : undefined
                  }
                  title={
                    p.open_conflict_count > 0 ? t('projectOverview.toProjectConflicts') : undefined
                  }
                >
                  {p.open_conflict_count}
                </Badge>
              </Table.Td>
              <Table.Td>
                {/* The commitment takes precedence over the lead-time warning: one is a
                    promise to somebody outside the company, the other is an internal
                    planning detail. A project can have both, and only the first belongs
                    in a management view at a glance. */}
                {p.commitment_breach ? (
                  <Tooltip
                    multiline
                    w={340}
                    label={
                      p.commitment_breach.hidden
                        ? t('projectOverview.breachHiddenDetail', {
                            committed: formatDate(p.commitment_breach.committed),
                            planned: formatDate(p.commitment_breach.planned_end),
                            derived: p.commitment_breach.derived_end
                              ? formatDate(p.commitment_breach.derived_end)
                              : '—',
                            days: p.commitment_breach.working_days_short,
                          })
                        : t('projectOverview.breachDetail', {
                            committed: formatDate(p.commitment_breach.committed),
                            planned: formatDate(p.commitment_breach.planned_end),
                            days: p.commitment_breach.working_days_short,
                          })
                    }
                  >
                    <Badge
                      color={p.commitment_breach.hidden ? 'orange' : 'red'}
                      variant="filled"
                      style={{ cursor: 'help' }}
                    >
                      {p.commitment_breach.hidden
                        ? t('projectOverview.breachHiddenBadge', {
                            days: p.commitment_breach.working_days_short,
                          })
                        : t('projectOverview.breachBadge', {
                            days: p.commitment_breach.working_days_short,
                          })}
                    </Badge>
                  </Tooltip>
                ) : p.late_work_packages.length === 0 ? (
                  <Text size="sm" c="dimmed">
                    —
                  </Text>
                ) : (
                  // The shortfall is shown in WORKING days because that is the unit
                  // the process is stated in and the number someone can act on.
                  // Calendar days would read larger and include days nobody works.
                  <Tooltip
                    multiline
                    w={320}
                    label={p.late_work_packages
                      .map((late) =>
                        t('projectOverview.latenessDetail', {
                          name: late.work_package_name,
                          entered: formatDate(late.entered_end),
                          derived: formatDate(late.derived_end),
                          days: late.working_days_short,
                        }),
                      )
                      .join('\n')}
                  >
                    <Badge color="orange" variant="light" style={{ cursor: 'help' }}>
                      {t('projectOverview.latenessBadge', {
                        count: p.late_work_packages.length,
                        days: Math.max(
                          ...p.late_work_packages.map((late) => late.working_days_short),
                        ),
                      })}
                    </Badge>
                  </Tooltip>
                )}
              </Table.Td>
              <Table.Td>
                {/* Float answers "how much room is there", which is a different
                    question from "is anything wrong". A project can be perfectly
                    consistent and still have no slack at all. */}
                {p.min_float_working_days === null ? (
                  <Text size="sm" c="dimmed">
                    —
                  </Text>
                ) : (
                  <Tooltip
                    label={t('projectOverview.floatDetail', {
                      days: p.min_float_working_days,
                      count: p.critical_work_package_count,
                    })}
                  >
                    <Badge
                      color={
                        p.min_float_working_days < 0
                          ? 'red'
                          : p.min_float_working_days === 0
                            ? 'orange'
                            : 'green'
                      }
                      variant="light"
                      style={{ cursor: 'help' }}
                    >
                      {t('projectOverview.floatBadge', {
                        days: p.min_float_working_days,
                      })}
                    </Badge>
                  </Tooltip>
                )}
              </Table.Td>
              <Table.Td>
                {/* Its own column rather than sharing with the commitment: a broken
                    dependency is an internal inconsistency somebody can fix by moving a
                    date, while a missed commitment is a fact about the outside world.
                    Collapsing them would make the actionable one look like the other. */}
                {p.dependency_violations.length === 0 ? (
                  <Text size="sm" c="dimmed">
                    —
                  </Text>
                ) : (
                  <Tooltip
                    multiline
                    w={360}
                    label={p.dependency_violations
                      .map((v) =>
                        t('projectOverview.dependencyDetail', {
                          successor: v.successor_name,
                          predecessor: v.predecessor_name,
                          earliest: formatDate(v.earliest_start),
                          start: formatDate(v.successor_start),
                          days: v.working_days_short,
                        }),
                      )
                      .join('\n')}
                  >
                    <Badge color="grape" variant="light" style={{ cursor: 'help' }}>
                      {t('projectOverview.dependencyBadge', {
                        count: p.dependency_violations.length,
                      })}
                    </Badge>
                  </Tooltip>
                )}
              </Table.Td>
              <Table.Td>
                <Group gap="xs">
                  <Button
                    size="xs"
                    variant="light"
                    leftSection={<IconChartBar size={14} />}
                    onClick={() => navigate(`/gantt?project=${p.project_id}`)}
                  >
                    {t('projectOverview.gantt')}
                  </Button>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </DataTable>
      )}
    </PageLayout>
  )
}
