/**
 * All projects on one time axis, each expandable to its work packages.
 *
 * WHY THIS REPLACED THE SINGLE-PROJECT VIEW: picking one project from a dropdown answers "when does
 * this project run" and nothing else. The question people actually bring here is where the GAPS are —
 * which needs every project on a shared axis at once. Showing all of them fully expanded would be
 * unreadable (three projects with eight packages each is 24 rows), so the default is one row per
 * project and the detail is opt-in per project. The old view is not lost: it is this one with a single
 * project expanded.
 *
 * WORK PACKAGES ARE FETCHED ON EXPAND, not upfront. Loading every project's packages to render bars
 * nobody asked to see would make the initial view cost O(projects) requests for data that is hidden.
 * Once fetched they are kept, so collapsing and re-expanding is free.
 *
 * THE AXIS INCLUDES LOADED WORK PACKAGES, not just project ranges. A work package may legitimately sit
 * outside its project's dates — the backend warns but saves it — and a bar outside the axis would be
 * clipped into invisibility. The cost is that expanding can widen the axis and shift bars sideways.
 * That is the right trade: a bar you cannot see is worse than one that moves.
 */

import { useCallback, useMemo, useState } from 'react'

import { useQueries } from '@tanstack/react-query'
import {
  Badge,
  Box,
  Group,
  Loader,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core'
import {
  IconAlertCircle,
  IconAlertTriangle,
  IconChevronDown,
  IconChevronRight,
} from '@tabler/icons-react'

import { getGanttData, type GanttWorkPackageBar } from '../../../api/gantt'
import { sortProjects, type ProjectSortKey } from './sortProjects'
import type { Project } from '../../../types/project'
import { useTranslation } from '../../../i18n'
import { queryKeys } from '../../../api/queryClient'
import {
  computeBarGeometry,
  computeTimeAxis,
  formatIsoDate,
  getSlotWidth,
  isCurrentSlot,
  type TimeScale,
  type TimeSlot,
} from '../timeAxis'
import { formatDate } from '../../../utils/date'
import type { DayAnchor } from '../../../utils/date'
import '../ResourceGanttChart.css'

interface Props {
  projects: Project[]
  timeScale: TimeScale
  onTimeScaleChange?: (scale: TimeScale) => void
  /** Called when a work package bar flagged as conflicting is clicked. */
  onConflictClick?: (bar: GanttWorkPackageBar) => void
  /**
   * Open conflicts per project id, for the COLLAPSED rows.
   *
   * Loaded by the caller, not here: work packages are fetched on expand, so a collapsed row
   * cannot derive this from the bars it holds. Without it a project containing a conflict looks
   * exactly like a healthy one on the screen a planner actually watches. An absent id renders
   * as no badge — the same as zero, which is why the caller clears the map on a failed load
   * rather than leaving a stale count that nothing is refreshing.
   */
  conflictCounts?: Map<string, number>
  /** Called when a project row's conflict badge is clicked. Separate from the bar handler,
   *  which carries a work package the project row does not have. */
  onProjectConflictClick?: (projectId: string) => void
}

/** What the rows are ordered by. */
type SortKey = ProjectSortKey

/**
 * Wide enough for a real project name.
 *
 * The first version used 220px with the text capped at 160, which truncated names like
 * "Mireo MDSB 4T Lackiererei ..." to an ellipsis at the point where they start to differ — four rows
 * read identically. That is worse here than in the old single-project view: there you PICKED a project
 * by name from a dropdown, here you have to tell rows apart at a glance. The tooltip on the name is
 * the backstop for names that are long even for this width.
 */
const LABEL_COLUMN_PX = 320
const LABEL_TEXT_MAX_PX = 250

export function ProjectsOverviewChart({
  projects,
  timeScale,
  onTimeScaleChange,
  onConflictClick,
  conflictCounts,
  onProjectConflictClick,
}: Props) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [sortKey, setSortKey] = useState<SortKey>('name')

  /**
   * WORK PACKAGES ARE FETCHED ON EXPAND, and this is where the migration's argument is at its plainest.
   *
   * The hand-written version maintained THREE PARALLEL MAPS to do it: `packagesByProject` as the cache,
   * `loadingIds` as the in-flight set, and `failedIds` as the error set — all keyed by project id, all
   * needing to be kept in step, with the "already fetched or being fetched" check written out by hand so
   * that re-expanding did not re-request. That is a per-key cache with a status per key, which is
   * precisely what a query cache is.
   *
   * THE QUERIES ARE KEYED ON `everExpanded`, NOT ON `expanded`, and that distinction is load-bearing.
   * Keying on `expanded` looks right and is subtly wrong: collapsing a project would UNMOUNT its query,
   * and re-expanding would mount a fresh observer that refetches whenever the entry is stale. The
   * original map kept the data unconditionally, so "collapsing and re-expanding is free" was an absolute
   * promise. Keeping the query mounted after the first expand preserves that promise exactly, instead of
   * making it depend on `staleTime`. A test pins it — it is how the regression was found.
   *
   * Per-project failure isolation is kept: failing to load ONE project must not blank the whole chart,
   * because the other projects are still valid data.
   *
   * What is new is that these bars now go stale when the plan changes. They are `gantt.projects(id)`, so
   * every plan-changing mutation reaches them through the `gantt` prefix. Before, an expanded project
   * kept drawing the dates it had when it was expanded, however much had been edited since — and this is
   * the screen people bring the "where are the gaps" question to.
   */
  const [everExpanded, setEverExpanded] = useState<Set<string>>(new Set())
  const fetchedIds = useMemo(() => [...everExpanded], [everExpanded])

  const packageQueries = useQueries({
    queries: fetchedIds.map((projectId) => ({
      queryKey: queryKeys.gantt.projects(projectId),
      queryFn: () => getGanttData(projectId),
      refetchInterval: 60_000,
    })),
  })

  const packagesByProject = useMemo(() => {
    const out: Record<string, GanttWorkPackageBar[]> = {}
    fetchedIds.forEach((projectId, index) => {
      const data = packageQueries[index]?.data
      if (data) out[projectId] = data.work_packages
    })
    return out
  }, [fetchedIds, packageQueries])

  const loadingIds = useMemo(
    () => new Set(fetchedIds.filter((_id, index) => packageQueries[index]?.isPending)),
    [fetchedIds, packageQueries],
  )

  const failedIds = useMemo(
    () => new Set(fetchedIds.filter((_id, index) => Boolean(packageQueries[index]?.error))),
    [fetchedIds, packageQueries],
  )

  const toggle = useCallback((projectId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(projectId)) next.delete(projectId)
      else next.add(projectId)
      return next
    })
    // Never removed: see the note above on why the query must stay mounted after the first expand.
    setEverExpanded((prev) => (prev.has(projectId) ? prev : new Set(prev).add(projectId)))
  }, [])

  const { timeSlots, minDate } = useMemo(() => {
    const items = [
      ...projects.map((p) => ({ start_date: p.start_date, end_date: p.end_date })),
      ...Object.entries(packagesByProject)
        .filter(([id]) => expanded.has(id))
        .flatMap(([, bars]) =>
          bars.map((b) => ({ start_date: b.start_date, end_date: b.end_date })),
        ),
    ]
    return computeTimeAxis(items, timeScale, t('gantt.weekPrefix'))
  }, [projects, packagesByProject, expanded, timeScale, t])

  const totalWidth = timeSlots.length * getSlotWidth(timeScale)

  // Sorting only reorders ROWS. The axis above is computed from the same set either way, so switching
  // the order never moves a bar horizontally — only which row it sits in changes.
  const sortedProjects = useMemo(() => sortProjects(projects, sortKey), [projects, sortKey])

  if (projects.length === 0) {
    return <Text c="dimmed">{t('gantt.noProjectsAvailable')}</Text>
  }

  return (
    <Stack gap="sm">
      <Group className="capado-gantt-toolbar">
        {onTimeScaleChange && (
          <SegmentedControl
            value={timeScale}
            onChange={(val) => onTimeScaleChange(val as TimeScale)}
            data={[
              { label: t('gantt.scaleDay'), value: 'day' },
              { label: t('gantt.scaleWeek'), value: 'week' },
              { label: t('gantt.scaleMonth'), value: 'month' },
            ]}
          />
        )}
        {/* Sorting is local state, so unlike the time scale it has no parent callback whose absence
            could hide it. */}
        <SegmentedControl
          value={sortKey}
          onChange={(val) => setSortKey(val as SortKey)}
          data={[
            { label: t('gantt.sortByName'), value: 'name' },
            { label: t('gantt.sortByStart'), value: 'start' },
            { label: t('gantt.sortByEnd'), value: 'end' },
          ]}
          aria-label={t('gantt.sortBy')}
        />
      </Group>

      <Paper withBorder p={0} className="capado-gantt-chart">
        <Box style={{ minWidth: totalWidth + LABEL_COLUMN_PX }}>
          {/* Time axis header */}
          <Box
            className="gantt-axis-header"
            style={{
              display: 'grid',
              gridTemplateColumns: `${LABEL_COLUMN_PX}px 1fr`,
              gap: 0,
              backgroundColor: 'var(--capado-subtle)',
            }}
          >
            <Box
              style={{
                padding: '4px 8px',
                fontWeight: 600,
                fontSize: '0.85rem',
                borderBottom: '1px solid var(--capado-border)',
              }}
            >
              {t('gantt.project')}
            </Box>
            <Box
              style={{
                display: 'grid',
                gridTemplateColumns: `repeat(${timeSlots.length}, ${getSlotWidth(timeScale)}px)`,
                borderBottom: '1px solid var(--capado-border)',
              }}
            >
              {timeSlots.map((slot, i) => (
                <Box
                  key={i}
                  className="gantt-axis-slot"
                  data-current={isCurrentSlot(slot, timeScale) || undefined}
                  data-weekend={
                    (timeScale === 'day' && [0, 6].includes(slot.start.getUTCDay())) || undefined
                  }
                  style={{
                    padding: '4px 2px',
                    fontSize: '0.7rem',
                    textAlign: 'center',
                    borderLeft: '1px solid var(--capado-border)',
                  }}
                >
                  {slot.label}
                </Box>
              ))}
            </Box>
          </Box>

          {/* One block per project: its own row, then its work packages when expanded. */}
          <Box
            style={{
              display: 'grid',
              gridTemplateColumns: `${LABEL_COLUMN_PX}px 1fr`,
              gap: 0,
            }}
          >
            {sortedProjects.map((project, projectIndex) => {
              const isOpen = expanded.has(project.id)
              const bars = packagesByProject[project.id] ?? []
              return (
                <ProjectBlock
                  key={project.id}
                  project={project}
                  striped={projectIndex % 2 === 1}
                  isOpen={isOpen}
                  isLoading={loadingIds.has(project.id)}
                  hasFailed={failedIds.has(project.id)}
                  bars={isOpen ? bars : []}
                  minDate={minDate}
                  timeSlots={timeSlots}
                  timeScale={timeScale}
                  onToggle={() => void toggle(project.id)}
                  onConflictClick={onConflictClick}
                  conflictCount={conflictCounts?.get(project.id) ?? 0}
                  onProjectConflictClick={onProjectConflictClick}
                />
              )
            })}
          </Box>
        </Box>
      </Paper>
    </Stack>
  )
}

interface ProjectBlockProps {
  project: Project
  striped: boolean
  isOpen: boolean
  isLoading: boolean
  hasFailed: boolean
  bars: GanttWorkPackageBar[]
  minDate: DayAnchor
  timeSlots: TimeSlot[]
  timeScale: TimeScale
  onToggle: () => void
  onConflictClick?: (bar: GanttWorkPackageBar) => void
  /** Open conflicts inside this project, 0 when unknown. */
  conflictCount: number
  onProjectConflictClick?: (projectId: string) => void
}

function ProjectBlock({
  project,
  striped,
  isOpen,
  isLoading,
  hasFailed,
  bars,
  minDate,
  timeSlots,
  timeScale,
  onToggle,
  onConflictClick,
  conflictCount,
  onProjectConflictClick,
}: ProjectBlockProps) {
  const { t, locale } = useTranslation()
  const geometry = computeBarGeometry(project, { minDate, timeSlots }, timeScale)
  // Two keys rather than one with a plural suffix: German needs "1 Konflikt" but
  // "2 Konflikten", and `interpolate` has no plural rules to lean on.
  const conflictLabel =
    conflictCount === 1
      ? t('gantt.projectConflictsTooltipOne')
      : t('gantt.projectConflictsTooltip', { count: conflictCount })

  return (
    <>
      {/* The project's own row */}
      <Box
        className="gantt-row"
        data-striped={striped || undefined}
        style={{ display: 'contents' }}
      >
        <Box
          className="gantt-row-cell"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            padding: '8px',
            border: 'none',
            background: 'var(--gantt-row-bg)',
            color: 'var(--capado-text)',
            cursor: 'pointer',
            textAlign: 'left',
            font: 'inherit',
            borderBottom: '1px solid var(--capado-border)',
          }}
        >
          <Tooltip
            label={project.name}
            withArrow
            events={{ hover: true, focus: true, touch: true }}
          >
            <UnstyledButton
              onClick={onToggle}
              aria-expanded={isOpen}
              data-testid={`project-toggle-${project.id}`}
              className="gantt-project-toggle"
            >
              {isOpen ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
              <Text size="sm" fw={600} truncate style={{ maxWidth: LABEL_TEXT_MAX_PX }}>
                {project.name}
              </Text>
              {isLoading && <Loader size={12} />}
            </UnstyledButton>
          </Tooltip>
          {conflictCount > 0 && (
            // On the NAME, not on the bar. The project bar is grey because it is a container that
            // occupies no resource; colouring it red would claim the project itself is the
            // conflict, and red on a bar already means "this work package is in conflict".
            // Same badge as the resource tables, so the signal reads the same everywhere.
            //
            // "Affected by", not "conflicts in": a conflict belongs to a RESOURCE over a period and
            // is attributed to every project whose work package is involved, so these counts do NOT
            // sum to the total. Measured on the test data: 2 distinct conflicts, 3 projects badged,
            // badges summing to 4. Wording that invited addition would make the planner's own
            // arithmetic disagree with the dashboard.
            <Tooltip label={conflictLabel} withArrow>
              <Badge
                component={onProjectConflictClick ? 'button' : 'span'}
                color="red"
                variant="light"
                size="xs"
                leftSection={<IconAlertTriangle size={10} />}
                data-testid={`project-conflicts-${project.id}`}
                style={{ cursor: onProjectConflictClick ? 'pointer' : 'default' }}
                role={onProjectConflictClick ? 'button' : undefined}
                aria-label={conflictLabel}
                onClick={
                  onProjectConflictClick ? () => onProjectConflictClick(project.id) : undefined
                }
              >
                {conflictCount}
              </Badge>
            </Tooltip>
          )}
          {hasFailed && (
            <Tooltip label={t('gantt.dataLoadFailed')} withArrow>
              <IconAlertCircle size={14} color="var(--mantine-color-red-6)" />
            </Tooltip>
          )}
        </Box>

        <BarLane minDate={minDate} timeSlots={timeSlots} timeScale={timeScale} height={40}>
          <Tooltip
            label={
              <Stack gap={2}>
                <Text size="xs" fw={600}>
                  {project.name}
                </Text>
                <Text size="xs">
                  {formatDate(project.start_date, locale)} – {formatDate(project.end_date, locale)}
                </Text>
              </Stack>
            }
            withArrow
            events={{ hover: true, focus: true, touch: true }}
          >
            <Box
              data-testid={`project-bar-${project.id}`}
              className="gantt-bar"
              role="img"
              tabIndex={0}
              aria-label={`${project.name}, ${formatDate(project.start_date, locale)} – ${formatDate(project.end_date, locale)}`}
              style={{
                position: 'absolute',
                top: 10,
                left: geometry.leftPx,
                width: geometry.widthPx,
                height: 20,
                // Grey, not blue: a project row is a container, and blue is the colour of an actual
                // scheduled work package. Using the same colour for both would suggest the project
                // itself occupies a resource, which it does not.
                backgroundColor:
                  'light-dark(var(--mantine-color-gray-5), var(--mantine-color-gray-7))',
                borderRadius: 6,
              }}
            />
          </Tooltip>
        </BarLane>
      </Box>

      {/* Work package rows, only while expanded */}
      {isOpen &&
        bars.map((bar, index) => (
          <Box
            key={bar.id}
            className="gantt-row"
            data-striped={index % 2 === 1 || undefined}
            style={{ display: 'contents' }}
          >
            <Box
              className="gantt-row-cell"
              style={{
                padding: '8px 8px 8px 28px',
                fontSize: '0.85rem',
                display: 'flex',
                alignItems: 'center',
                borderBottom: '1px solid var(--capado-border)',
                backgroundColor: 'var(--gantt-row-bg)',
              }}
            >
              <Tooltip label={bar.name} withArrow openDelay={300}>
                <Text size="sm" truncate style={{ maxWidth: LABEL_TEXT_MAX_PX - 20 }}>
                  {bar.name}
                </Text>
              </Tooltip>
            </Box>
            <BarLane minDate={minDate} timeSlots={timeSlots} timeScale={timeScale} height={36}>
              <WorkPackageBar
                bar={bar}
                minDate={minDate}
                timeSlots={timeSlots}
                timeScale={timeScale}
                onConflictClick={onConflictClick}
              />
            </BarLane>
          </Box>
        ))}

      {isOpen && !isLoading && !hasFailed && bars.length === 0 && (
        <>
          <Box
            className="gantt-row-cell"
            style={{
              padding: '8px 8px 8px 28px',
              borderBottom: '1px solid var(--capado-border)',
            }}
          >
            <Text size="xs" c="dimmed">
              {t('gantt.noWorkPackagesInProject')}
            </Text>
          </Box>
          <Box
            className="gantt-row-cell"
            style={{
              borderBottom: '1px solid var(--capado-border)',
            }}
          />
        </>
      )}
    </>
  )
}

interface BarLaneProps {
  minDate: DayAnchor
  timeSlots: TimeSlot[]
  timeScale: TimeScale
  height: number
  children: React.ReactNode
}

/** The right-hand cell: background grid for one row, with the bar positioned on top. */
function BarLane({ timeSlots, timeScale, height, children }: BarLaneProps) {
  return (
    <Box
      className="gantt-row-cell"
      style={{
        position: 'relative',
        height,
        borderBottom: '1px solid var(--capado-border)',
        display: 'grid',
        gridTemplateColumns: `repeat(${timeSlots.length}, ${getSlotWidth(timeScale)}px)`,
        backgroundColor: 'var(--gantt-row-bg)',
      }}
    >
      {timeSlots.map((slot, i) => (
        <Box
          key={i}
          className="gantt-grid-slot"
          data-weekend={
            (timeScale === 'day' && [0, 6].includes(slot.start.getUTCDay())) || undefined
          }
          data-testid={timeScale === 'day' ? `gantt-cell-${formatIsoDate(slot.start)}` : undefined}
          data-current={isCurrentSlot(slot, timeScale) ? 'true' : undefined}
          style={{
            borderLeft: '1px solid var(--capado-border)',
            height: '100%',
          }}
        />
      ))}
      {children}
    </Box>
  )
}

interface WorkPackageBarProps {
  bar: GanttWorkPackageBar
  minDate: DayAnchor
  timeSlots: TimeSlot[]
  timeScale: TimeScale
  onConflictClick?: (bar: GanttWorkPackageBar) => void
}

function WorkPackageBar({
  bar,
  minDate,
  timeSlots,
  timeScale,
  onConflictClick,
}: WorkPackageBarProps) {
  const { leftPx, widthPx } = computeBarGeometry(bar, { minDate, timeSlots }, timeScale)
  // Red still means conflict, exactly as in the other charts. Nothing else claims a colour.
  const { t, locale } = useTranslation()
  const color = bar.has_conflict
    ? 'var(--mantine-color-red-6)'
    : 'var(--mantine-primary-color-filled)'

  return (
    <Tooltip
      label={
        <Stack gap={2}>
          <Text size="xs" fw={600}>
            {bar.name}
          </Text>
          <Text size="xs">
            {formatDate(bar.start_date, locale)} – {formatDate(bar.end_date, locale)}
          </Text>
        </Stack>
      }
      withArrow
      events={{ hover: true, focus: true, touch: true }}
    >
      <Box
        data-testid={`gantt-bar-${bar.id}`}
        className="gantt-bar"
        data-conflict={bar.has_conflict || undefined}
        role={bar.has_conflict && onConflictClick ? 'button' : 'img'}
        tabIndex={0}
        aria-label={`${bar.has_conflict ? t('gantt.conflictDetected') + ': ' : ''}${bar.name}, ${formatDate(bar.start_date, locale)} – ${formatDate(bar.end_date, locale)}`}
        onKeyDown={(event) => {
          if (bar.has_conflict && onConflictClick && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault()
            onConflictClick(bar)
          }
        }}
        onClick={() => bar.has_conflict && onConflictClick?.(bar)}
        style={{
          position: 'absolute',
          top: 8,
          left: leftPx,
          width: widthPx,
          height: 20,
          backgroundColor: color,
          borderRadius: 6,
          cursor: bar.has_conflict ? 'pointer' : 'default',
        }}
      />
    </Tooltip>
  )
}
