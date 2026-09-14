/**
 * Gantt section: Work packages as horizontal bars on a time axis.
 * Three perspectives at the same level: Project, Personal, Infrastructure.
 * Each shows a group/project selector and then the appropriate Gantt chart.
 *
 * The data loading logic is unified: each perspective loads a list of
 * selectable options, then fetches Gantt data for the selected option.
 */

import { useEffect, useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { Alert, Loader, SegmentedControl, Select, Stack, Text } from '@mantine/core'
import { IconAlertCircle } from '@tabler/icons-react'
import axios from 'axios'
import { getProjects } from '../../api/projects'
import { getProjectOverview } from '../../api/projectOverview'
import { getGroups } from '../../api/resources'
import { getInfraGroupGanttData, getDepartmentGanttData } from '../../api/ganttResources'
import type { ResourceGanttResponse } from '../../api/ganttResources'
import type { Project } from '../../types/project'
import type { ResourceGroup } from '../../types/resource'
import { ResourceGanttChart } from './ResourceGanttChart'
import { ProjectsOverviewChart } from './projectGantt/ProjectsOverviewChart'
import type { TimeScale } from './timeAxis'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'

type Perspective = 'project' | 'personal' | 'infrastructure'

export function GanttSection() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [perspective, setPerspective] = useState<Perspective>('project')
  const [timeScale, setTimeScale] = useState<TimeScale>('week')

  /**
   * Open conflicts per project id, for the COLLAPSED project rows.
   *
   * Work packages are fetched on expand, so a collapsed row cannot derive this from the
   * bars it holds — without it, a project containing a conflict looks exactly like a
   * healthy one, on the screen a planner actually watches.
   */
  const [selectedId, setSelectedId] = useState<string | null>(() => {
    return searchParams.get('project') ?? null
  })

  const [error, setError] = useState<string | null>(null)

  const handlePerspectiveChange = (val: string) => {
    setPerspective(val as Perspective)
    setSelectedId(null)
    setError(null)
  }

  /**
   * THE PERSPECTIVE IS IN THE KEY, so switching tabs cannot render one perspective's data under
   * another's heading — which is what the `setOptions([])` / `setResourceGantt(null)` clearing on every
   * switch existed to prevent. `enabled` does that clearing by construction.
   */
  const projectsQuery = useQuery({
    queryKey: queryKeys.projects.list(),
    queryFn: () => getProjects(),
    enabled: perspective === 'project',
  })

  /**
   * Conflict counts come from a SECOND request, deliberately a separate query rather than awaited with
   * the project list: the chart is useful without them, and a failing or slow overview must not keep
   * the bars off the screen.
   *
   * A missing count renders as no badge, which looks the same as "no conflicts" — acceptable only
   * because its failure is reported below, and because it is now RETRIED on the same terms as anything
   * else instead of only on a perspective switch.
   */
  const overviewQuery = useQuery({
    queryKey: queryKeys.dashboard.projectOverview(),
    queryFn: () => getProjectOverview(),
    enabled: perspective === 'project',
  })

  const groupsQuery = useQuery({
    queryKey: queryKeys.resources.groups(perspective),
    queryFn: () => getGroups(perspective as 'personal' | 'infrastructure'),
    enabled: perspective !== 'project',
  })

  const projects: Project[] = projectsQuery.data ?? []
  const groups: ResourceGroup[] = groupsQuery.data ?? []

  const options = useMemo(
    () =>
      perspective === 'project'
        ? projects.map((proj) => ({ value: proj.id, label: proj.name }))
        : groups.map((g) => ({ value: g.id, label: g.name })),
    [perspective, projects, groups],
  )

  const optionsLoading = perspective === 'project' ? projectsQuery.isPending : groupsQuery.isPending

  // Empty rather than left stale on failure: a count from an earlier load would claim a project is in
  // trouble on evidence that is no longer being refreshed.
  const conflictCounts = useMemo(
    () =>
      new Map(
        (overviewQuery.data?.projects ?? []).map((item) => [
          item.project_id,
          item.open_conflict_count,
        ]),
      ),
    [overviewQuery.data],
  )
  const conflictCountsFailed = Boolean(overviewQuery.error)

  const selectedGroup = groups.find((g) => g.id === selectedId)

  /**
   * One group's resource Gantt. The project perspective has no selection: it renders every project and
   * fetches work packages per expanded project, which ProjectsOverviewChart owns.
   *
   * The department endpoint is addressed by NAME and the infrastructure one by id, so the key carries
   * whichever this perspective uses — two perspectives over one group must not share an entry.
   */
  const resourceGanttQuery = useQuery({
    queryKey:
      perspective === 'infrastructure'
        ? queryKeys.gantt.infraGroup(selectedGroup?.id ?? 'none')
        : queryKeys.gantt.department(selectedGroup?.name ?? 'none'),
    queryFn: () =>
      perspective === 'infrastructure'
        ? getInfraGroupGanttData(selectedGroup!.id)
        : getDepartmentGanttData(selectedGroup!.name),
    enabled: perspective !== 'project' && Boolean(selectedGroup),
  })

  const resourceGantt: ResourceGanttResponse | null = resourceGanttQuery.data ?? null
  const loading = Boolean(selectedGroup) && resourceGanttQuery.isPending

  useEffect(() => {
    const queryError = groupsQuery.error ?? projectsQuery.error
    if (queryError) {
      setError(
        axios.isAxiosError(queryError)
          ? (queryError.response?.data?.detail ?? t('gantt.resourceLoadFailed'))
          : t('gantt.resourceLoadFailed'),
      )
      return
    }
    if (resourceGanttQuery.error) {
      const err = resourceGanttQuery.error
      setError(
        axios.isAxiosError(err)
          ? (err.response?.data?.detail ?? t('gantt.dataLoadFailed'))
          : t('gantt.dataLoadFailed'),
      )
    }
  }, [groupsQuery.error, projectsQuery.error, resourceGanttQuery.error, t])

  const isOptionsEmpty = options.length === 0 && !optionsLoading
  const isEmpty = perspective !== 'project' && resourceGantt && resourceGantt.projects.length === 0

  return (
    <Stack gap="md">
      <SegmentedControl
        value={perspective}
        onChange={handlePerspectiveChange}
        data={[
          { label: t('planning.ganttProject'), value: 'project' },
          { label: t('resources.personal'), value: 'personal' },
          { label: t('resources.infrastructure'), value: 'infrastructure' },
        ]}
      />

      {/* The resource perspectives still pick ONE group: a resource chart of every group at once
          would mix unrelated capacity. The project perspective no longer has a Select, because
          seeing gaps requires every project on one axis — it shows them all and lets you expand. */}
      {perspective !== 'project' && (
        <Select
          label={t('gantt.selectGroup')}
          placeholder={
            isOptionsEmpty ? t('gantt.noResourcesAvailable') : t('gantt.selectGroupPlaceholder')
          }
          data={options}
          value={selectedId}
          onChange={setSelectedId}
          searchable
          clearable
          disabled={isOptionsEmpty}
          style={{ minWidth: 300 }}
        />
      )}

      {error && (
        <Alert icon={<IconAlertCircle size={16} />} color="red">
          {error}
        </Alert>
      )}

      {loading && <Loader />}

      {!loading && perspective !== 'project' && !selectedId && !error && (
        <Text c="dimmed">{t('gantt.selectResourcePrompt')}</Text>
      )}

      {!loading && isEmpty && <Text c="dimmed">{t('gantt.noAssignments')}</Text>}

      {/* Projects overview: all projects, expandable to their work packages. */}
      {perspective === 'project' && !optionsLoading && (
        <>
          {/* A failed count must SAY so. An absent badge is indistinguishable from "no
              conflicts", so silence here would report a healthy plan on no evidence — the
              same shape of error as a green gate that never ran. */}
          {conflictCountsFailed && (
            <Text size="xs" c="dimmed" mb="xs">
              {t('gantt.projectConflictsUnavailable')}
            </Text>
          )}
          <ProjectsOverviewChart
            projects={projects}
            timeScale={timeScale}
            onTimeScaleChange={setTimeScale}
            onConflictClick={() => navigate('/planning')}
            conflictCounts={conflictCounts}
            onProjectConflictClick={() => navigate('/planning')}
          />
        </>
      )}

      {/* Resource Gantt (personal & infrastructure) */}
      {!loading &&
        perspective !== 'project' &&
        resourceGantt &&
        resourceGantt.projects.length > 0 && (
          <ResourceGanttChart
            data={resourceGantt}
            timeScale={timeScale}
            onTimeScaleChange={setTimeScale}
            onConflictClick={(bar) => {
              if (bar.resource_id) {
                navigate(`/planning?resource=${bar.resource_id}`)
              } else {
                navigate('/planning')
              }
            }}
          />
        )}
    </Stack>
  )
}
