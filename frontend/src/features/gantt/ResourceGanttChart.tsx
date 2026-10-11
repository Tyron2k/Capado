/**
 * ResourceGanttChart: Gantt chart for the resource perspective.
 * Shows work packages as horizontal bars on a time axis.
 *
 * TWO GROUPINGS, and they answer different questions. Grouped by PROJECT (the original) the row is a
 * work package and the heading is the project: "when does this project run". Grouped by RESOURCE the
 * row is one resource and the heading is its name: "what is standing on track 42, and when is it
 * FREE". Only the second makes a gap visible, because occupancy of one resource is then confined to
 * one row instead of scattered across project headings.
 *
 * Both are folds of the same response — see groupByResource — so they cannot contradict each other.
 */

import React, { useMemo, useState } from 'react'
import { Box, Group, Paper, SegmentedControl, Text, Tooltip, Stack } from '@mantine/core'
import type { ResourceGanttResponse, ResourceGanttBar } from '../../api/ganttResources'
import { groupByResource } from './groupByResource'
import {
  computeBarGeometry,
  computeTimeAxis,
  formatIsoDate,
  getSlotWidth,
  isCurrentSlot,
  type TimeScale,
  type TimeSlot,
} from './timeAxis'
import { useTranslation } from '../../i18n'
import { formatDate } from '../../utils/date'
import type { DayAnchor } from '../../utils/date'
import './ResourceGanttChart.css'

type Grouping = 'project' | 'resource'

interface ResourceGanttChartProps {
  data: ResourceGanttResponse
  timeScale: TimeScale
  onTimeScaleChange?: (scale: TimeScale) => void
  /** Called when the user clicks on a conflict-affected bar. */
  onConflictClick?: (bar: ResourceGanttBar) => void
}

export function ResourceGanttChart({
  data,
  timeScale,
  onTimeScaleChange,
  onConflictClick,
}: ResourceGanttChartProps) {
  const { t } = useTranslation()
  const [grouping, setGrouping] = useState<Grouping>('project')
  // Flatten all work packages to compute the time axis
  const allBars = useMemo(() => data.projects.flatMap((p) => p.work_packages), [data])

  // Both groupings share ONE axis, computed from every bar. Deriving it per group would give each
  // row block its own scale, and two bars at the same horizontal position would mean different dates
  // — which would make the whole point of the view, comparing occupancy over time, a lie.
  const resourceGroups = useMemo(() => groupByResource(data), [data])

  const { timeSlots, minDate } = useMemo(
    () => computeTimeAxis(allBars, timeScale, t('gantt.weekPrefix')),
    [allBars, timeScale, t],
  )

  const totalWidth = timeSlots.length * getSlotWidth(timeScale)

  return (
    <Stack gap="sm">
      <Group className="capado-gantt-toolbar">
        {/* Time scale control */}
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
        {/* Grouping control. Always shown, unlike the time scale: the grouping is local state, so
            there is no parent callback whose absence could hide it. */}
        <SegmentedControl
          value={grouping}
          onChange={(val) => setGrouping(val as Grouping)}
          data={[
            { label: t('gantt.groupByProject'), value: 'project' },
            { label: t('gantt.groupByResource'), value: 'resource' },
          ]}
          aria-label={t('gantt.grouping')}
        />
      </Group>

      <Paper withBorder p={0} className="capado-gantt-chart">
        <Box style={{ minWidth: totalWidth + 200 }}>
          {/* Time axis header */}
          <Box
            className="gantt-axis-header"
            style={{
              display: 'grid',
              gridTemplateColumns: `200px 1fr`,
              gap: 0,
              backgroundColor: 'var(--capado-subtle)',
            }}
          >
            <Box
              style={{
                borderBottom: '1px solid var(--capado-border)',
                padding: '4px 8px',
                fontWeight: 600,
                fontSize: '0.85rem',
                backgroundColor: 'var(--capado-subtle)',
              }}
            >
              {t('gantt.workPackage')}
            </Box>
            <Box
              style={{
                display: 'grid',
                gridTemplateColumns: `repeat(${timeSlots.length}, ${getSlotWidth(timeScale)}px)`,
                borderBottom: '1px solid var(--capado-border)',
              }}
            >
              {timeSlots.map((slot) => {
                const isCurrent = isCurrentSlot(slot, timeScale)
                return (
                  <Box
                    key={slot.label}
                    className="gantt-axis-slot"
                    data-weekend={
                      (timeScale === 'day' && [0, 6].includes(slot.start.getUTCDay())) || undefined
                    }
                    data-testid={
                      timeScale === 'day' ? `axis-slot-${formatIsoDate(slot.start)}` : undefined
                    }
                    data-current={isCurrent ? 'true' : undefined}
                    style={{
                      padding: '4px 2px',
                      textAlign: 'center',
                      fontSize: '0.75rem',
                      borderLeft: '1px solid var(--capado-border)',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      fontWeight: isCurrent ? 700 : undefined,
                    }}
                  >
                    {slot.label}
                  </Box>
                )
              })}
            </Box>
          </Box>

          {/* Groups. The two branches differ only in what the heading and the row label say — the
              row component, the axis and the geometry are shared, so the two views cannot drift
              apart visually. */}
          {(grouping === 'project'
            ? data.projects.map((p) => ({
                key: p.project_id,
                heading: p.project_name,
                testId: `project-heading-${p.project_id}`,
                rows: p.work_packages.map((bar) => ({ bar, label: bar.name })),
              }))
            : resourceGroups.map((r) => ({
                key: r.resource_id,
                heading: r.resource_name,
                testId: `resource-heading-${r.resource_id}`,
                // Grouped by resource the project is the interesting label: the row already IS the
                // resource, so repeating its name would waste the only wide column.
                rows: r.bars.map((bar) => ({ bar, label: bar.project_name })),
              }))
          ).map((group) => (
            <Box key={group.key}>
              {/* Group heading */}
              <Box
                style={{
                  padding: '8px',
                  backgroundColor: 'var(--capado-subtle)',
                  borderBottom: '1px solid var(--capado-border)',
                  fontWeight: 600,
                  fontSize: '0.9rem',
                }}
                data-testid={group.testId}
              >
                {group.heading}
              </Box>

              {/* Rows */}
              <Box
                style={{
                  display: 'grid',
                  gridTemplateColumns: `200px 1fr`,
                  gap: 0,
                }}
              >
                {group.rows.map(({ bar, label }, index) => (
                  <ResourceGanttRow
                    key={bar.id}
                    bar={bar}
                    label={label}
                    striped={index % 2 === 1}
                    minDate={minDate}
                    timeSlots={timeSlots}
                    timeScale={timeScale}
                    onConflictClick={onConflictClick}
                  />
                ))}
              </Box>
            </Box>
          ))}
        </Box>
      </Paper>
    </Stack>
  )
}

// --- Tooltip Content Helper (exported for testing) ---

// eslint-disable-next-line react-refresh/only-export-components
export function buildTooltipContent(bar: ResourceGanttBar): {
  name: string
  resourceName: string
  dateRange: string
  allocationPercent: number
  hasConflict: boolean
} {
  return {
    name: bar.name,
    resourceName: bar.resource_name,
    dateRange: `${bar.start_date} – ${bar.end_date}`,
    allocationPercent: bar.allocation_percent,
    hasConflict: bar.has_conflict,
  }
}

// --- Resource Gantt Row ---

interface ResourceGanttRowProps {
  bar: ResourceGanttBar
  /** What the left column says — the work package when grouped by project, the project otherwise. */
  label: string
  /** Every second row, for zebra striping. */
  striped: boolean
  minDate: DayAnchor
  timeSlots: TimeSlot[]
  timeScale: TimeScale
  onConflictClick?: (bar: ResourceGanttBar) => void
}

const ResourceGanttRow = React.memo(function ResourceGanttRow({
  bar,
  label,
  striped,
  minDate,
  timeSlots,
  timeScale,
  onConflictClick,
}: ResourceGanttRowProps) {
  const { leftPx, widthPx } = computeBarGeometry(bar, { minDate, timeSlots }, timeScale)

  const { t, locale } = useTranslation()
  const barColor = bar.has_conflict
    ? 'var(--mantine-color-red-6)'
    : 'var(--mantine-primary-color-filled)'

  const showLabel = widthPx > 120

  // Losing your row while scanning sideways is the actual complaint behind "can we colour the bars".
  // Zebra plus hover fixes it WITHOUT spending colour, which here already means something: red is a
  // conflict. Giving each work package its own hue would overwrite the one signal that says where it
  // hurts.
  //
  // Hover is driven by CSS on a shared class rather than React state so that BOTH grid cells of one
  // row light up together — they are siblings in the grid, not children of a row element, so
  // :hover on one cannot reach the other. Re-rendering on mousemove would also be wasteful on a
  // chart with hundreds of rows.

  return (
    <Box className="gantt-row" data-striped={striped || undefined} style={{ display: 'contents' }}>
      {/* Label cell */}
      <Box
        className="gantt-row-cell"
        data-row-id={bar.id}
        style={{
          padding: '8px',
          borderBottom: '1px solid var(--capado-border)',
          fontSize: '0.85rem',
          display: 'flex',
          alignItems: 'center',
          backgroundColor: 'var(--gantt-row-bg)',
        }}
      >
        <Text size="sm" truncate style={{ maxWidth: 180 }}>
          {label}
        </Text>
      </Box>

      {/* Bar area */}
      <Box
        className="gantt-row-cell"
        data-row-id={bar.id}
        style={{
          position: 'relative',
          height: 40,
          borderBottom: '1px solid var(--capado-border)',
          display: 'grid',
          gridTemplateColumns: `repeat(${timeSlots.length}, ${getSlotWidth(timeScale)}px)`,
          backgroundColor: 'var(--gantt-row-bg)',
        }}
      >
        {/* Background cells */}
        {timeSlots.map((slot, i) => {
          const isCurrent = isCurrentSlot(slot, timeScale)

          return (
            <Box
              key={i}
              className="gantt-grid-slot"
              data-weekend={
                (timeScale === 'day' && [0, 6].includes(slot.start.getUTCDay())) || undefined
              }
              data-testid={
                timeScale === 'day' ? `gantt-cell-${formatIsoDate(slot.start)}` : undefined
              }
              data-current={isCurrent ? 'true' : undefined}
              style={{
                position: 'relative',
                borderLeft: '1px solid var(--capado-border)',
                height: '100%',
              }}
            />
          )
        })}

        {/* The bar */}
        <Tooltip
          label={
            <Stack gap={2}>
              <Text size="xs" fw={600}>
                {bar.name}
              </Text>
              <Text size="xs">
                {t('gantt.tooltipResource')}: {bar.resource_name}
              </Text>
              <Text size="xs">
                {formatDate(bar.start_date, locale)} – {formatDate(bar.end_date, locale)}
              </Text>
              <Text size="xs">
                {t('gantt.tooltipAllocation')}: {bar.allocation_percent}%
              </Text>
              {bar.has_conflict && (
                <Text size="xs" c="var(--capado-danger)">
                  {t('gantt.conflictDetected')}
                </Text>
              )}
            </Stack>
          }
          multiline
          withArrow
          position="top"
          events={{ hover: true, focus: true, touch: true }}
        >
          <Box
            data-testid={`gantt-bar-${bar.id}`}
            className="gantt-bar"
            data-conflict={bar.has_conflict || undefined}
            role={bar.has_conflict && onConflictClick ? 'button' : 'img'}
            tabIndex={0}
            aria-label={
              bar.has_conflict
                ? `${t('gantt.conflictDetected')}: ${bar.name}, ${formatDate(bar.start_date, locale)} – ${formatDate(bar.end_date, locale)}`
                : `${bar.name}, ${formatDate(bar.start_date, locale)} – ${formatDate(bar.end_date, locale)}`
            }
            onClick={() => {
              if (bar.has_conflict && onConflictClick) {
                onConflictClick(bar)
              }
            }}
            onKeyDown={(event) => {
              if (!bar.has_conflict || !onConflictClick) return
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onConflictClick(bar)
              }
            }}
            style={{
              position: 'absolute',
              top: 8,
              left: leftPx,
              width: widthPx,
              height: 24,
              backgroundColor: barColor,
              borderRadius: 6,
              cursor: bar.has_conflict && onConflictClick ? 'pointer' : 'default',
              display: 'flex',
              alignItems: 'center',
              paddingLeft: 6,
              paddingRight: 6,
              overflow: 'hidden',
            }}
          >
            {showLabel && (
              <Text
                size="xs"
                c={bar.has_conflict ? '#172033' : 'var(--mantine-primary-color-contrast)'}
                truncate
                style={{
                  lineHeight: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {bar.name}
              </Text>
            )}
          </Box>
        </Tooltip>
      </Box>
    </Box>
  )
})
