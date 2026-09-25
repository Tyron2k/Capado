/**
 * Tests for the all-projects overview.
 *
 * The behaviours worth pinning are the ones that make it usable rather than merely present:
 * collapsed by default (or the view is the 24-row wall it exists to avoid), work packages fetched on
 * expand and only once, and one project failing to load must not blank the chart — the other projects
 * are still valid data.
 *
 * All fixtures are inline and fictional.
 */

import type { ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'

import { createTestQueryClient } from '../../../testUtils/queryClient'
import { MantineProvider } from '@mantine/core'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const getGanttData = vi.fn()

vi.mock('../../../api/gantt', () => ({
  getGanttData: (id: string) => getGanttData(id),
}))

vi.mock('../../../i18n', () => {
  const t = (key: string) => key
  return { useTranslation: () => ({ t }) }
})

import { ProjectsOverviewChart } from './ProjectsOverviewChart'
import type { Project } from '../../../types/project'

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

function project(id: string, name: string, start: string, end: string): Project {
  return {
    id,
    name,
    folder_id: null,
    position: 0,
    external_ref: null,
    start_date: start,
    end_date: end,
    committed_delivery_date: null,
  } as Project
}

const projects = [
  project('p-1', 'Order 4711', '2026-03-01', '2026-05-31'),
  project('p-2', 'Order 4712', '2026-06-01', '2026-08-31'),
]

function renderChart(items = projects) {
  return render(
    (
      <QueryClientProvider client={createTestQueryClient()}>
        <MantineProvider>
          <ProjectsOverviewChart projects={items} timeScale="month" />
        </MantineProvider>
      </QueryClientProvider>
    ) as ReactNode,
  )
}

describe('ProjectsOverviewChart', () => {
  beforeEach(() => {
    getGanttData.mockReset()
    getGanttData.mockResolvedValue({
      project_id: 'p-1',
      project_name: 'Order 4711',
      work_packages: [
        {
          id: 'wp-1',
          name: 'Painting',
          start_date: '2026-03-05',
          end_date: '2026-03-20',
          resources: [],
          resource_assignments: [],
          has_conflict: false,
        },
      ],
    })
  })

  it('shows every project without being asked to select one', () => {
    renderChart()

    expect(screen.getByTestId('project-bar-p-1')).toBeTruthy()
    expect(screen.getByTestId('project-bar-p-2')).toBeTruthy()
  })

  it('starts collapsed and fetches nothing', () => {
    renderChart()

    // The whole point of the default: all projects, no work packages, no requests.
    expect(getGanttData).not.toHaveBeenCalled()
    expect(screen.queryByTestId('gantt-bar-wp-1')).toBeNull()
  })

  it('fetches work packages only for the project that was expanded', async () => {
    renderChart()

    fireEvent.click(screen.getByTestId('project-toggle-p-1'))

    await waitFor(() => expect(screen.getByTestId('gantt-bar-wp-1')).toBeTruthy())
    expect(getGanttData).toHaveBeenCalledTimes(1)
    expect(getGanttData).toHaveBeenCalledWith('p-1')
  })

  it('does not refetch when the same project is collapsed and reopened', async () => {
    renderChart()

    fireEvent.click(screen.getByTestId('project-toggle-p-1'))
    await waitFor(() => expect(screen.getByTestId('gantt-bar-wp-1')).toBeTruthy())

    fireEvent.click(screen.getByTestId('project-toggle-p-1'))
    await waitFor(() => expect(screen.queryByTestId('gantt-bar-wp-1')).toBeNull())
    fireEvent.click(screen.getByTestId('project-toggle-p-1'))

    await waitFor(() => expect(screen.getByTestId('gantt-bar-wp-1')).toBeTruthy())
    // Kept, not re-requested: reopening is free.
    expect(getGanttData).toHaveBeenCalledTimes(1)
  })

  it('refreshes previously expanded work packages every minute', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    try {
      const view = renderChart()
      fireEvent.click(screen.getByTestId('project-toggle-p-1'))
      await waitFor(() => expect(getGanttData).toHaveBeenCalledTimes(1))

      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000)
      })

      await waitFor(() => expect(getGanttData).toHaveBeenCalledTimes(2))
      view.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('reports aria-expanded so the toggle is not a mystery to a screen reader', async () => {
    renderChart()
    const toggle = screen.getByTestId('project-toggle-p-1')

    expect(toggle.getAttribute('aria-expanded')).toBe('false')

    fireEvent.click(toggle)

    await waitFor(() => expect(toggle.getAttribute('aria-expanded')).toBe('true'))
  })

  it('keeps the other projects when one fails to load', async () => {
    getGanttData.mockRejectedValue(new Error('boom'))
    renderChart()

    fireEvent.click(screen.getByTestId('project-toggle-p-1'))

    // The failure belongs to one row. Blanking the chart would discard the other project's bar,
    // which is still perfectly good data.
    await waitFor(() => expect(screen.getByTestId('project-bar-p-2')).toBeTruthy())
    expect(screen.getByTestId('project-bar-p-1')).toBeTruthy()
  })

  it('says so rather than drawing nothing when there are no projects', () => {
    renderChart([])

    expect(screen.getByText('gantt.noProjectsAvailable')).toBeTruthy()
  })

  it('reorders the rows when the sort is changed', () => {
    // Order 4712 starts later but sorts first by name, so the two orders are distinguishable.
    const items = [
      project('p-2', 'Aaa late start', '2026-09-01', '2026-09-30'),
      project('p-1', 'Zzz early start', '2026-01-01', '2026-01-31'),
    ]
    renderChart(items)

    const rowOrder = () =>
      screen.getAllByTestId(/^project-toggle-/).map((el) => el.getAttribute('data-testid'))

    expect(rowOrder()).toEqual(['project-toggle-p-2', 'project-toggle-p-1'])

    fireEvent.click(screen.getByRole('radio', { name: /gantt.sortByStart/i }))

    expect(rowOrder()).toEqual(['project-toggle-p-1', 'project-toggle-p-2'])
  })

  it('keeps a project expanded when the sort changes', async () => {
    renderChart()

    fireEvent.click(screen.getByTestId('project-toggle-p-1'))
    await waitFor(() => expect(screen.getByTestId('gantt-bar-wp-1')).toBeTruthy())

    fireEvent.click(screen.getByRole('radio', { name: /gantt.sortByEnd/i }))

    // Expansion is keyed by project id, not by row position — reordering must not collapse it or,
    // worse, transfer the open state to whichever project moved into that slot.
    expect(screen.getByTestId('gantt-bar-wp-1')).toBeTruthy()
  })
})

/**
 * Conflict counts on the COLLAPSED project row.
 *
 * This is the whole point of the feature: work packages are fetched on expand, so a collapsed
 * row cannot derive conflict state from the bars it holds, and a project containing a conflict
 * looked exactly like a healthy one. The count therefore comes in as a prop.
 */
describe('ProjectsOverviewChart conflict counts', () => {
  function renderWithCounts(counts: Map<string, number>, onBadgeClick?: (id: string) => void) {
    return render(
      (
        <QueryClientProvider client={createTestQueryClient()}>
          <MantineProvider>
            <ProjectsOverviewChart
              projects={projects}
              timeScale="month"
              conflictCounts={counts}
              onProjectConflictClick={onBadgeClick}
            />
          </MantineProvider>
        </QueryClientProvider>
      ) as ReactNode,
    )
  }

  it('shows the count on a collapsed project row', () => {
    renderWithCounts(new Map([['p-1', 3]]))

    // Collapsed: no work package bar is rendered, so this signal cannot have come from one.
    expect(screen.queryByTestId('gantt-bar-wp-1')).toBeNull()
    expect(screen.getByTestId('project-conflicts-p-1').textContent).toContain('3')
  })

  it('shows no badge for a project with zero conflicts', () => {
    renderWithCounts(
      new Map([
        ['p-1', 3],
        ['p-2', 0],
      ]),
    )

    expect(screen.getByTestId('project-conflicts-p-1')).toBeTruthy()
    expect(screen.queryByTestId('project-conflicts-p-2')).toBeNull()
  })

  it('shows no badge for a project the counts do not mention', () => {
    // An absent id is treated as zero. That is a real limitation, not a nicety: it means a
    // FAILED load looks like a healthy plan, which is why the caller clears the map and says so
    // rather than leaving stale counts behind.
    renderWithCounts(new Map([['p-1', 1]]))

    expect(screen.queryByTestId('project-conflicts-p-2')).toBeNull()
  })

  it('does not expand the project when its badge is clicked', () => {
    const onBadgeClick = vi.fn()
    renderWithCounts(new Map([['p-1', 2]]), onBadgeClick)

    fireEvent.click(screen.getByTestId('project-conflicts-p-1'))

    expect(onBadgeClick).toHaveBeenCalledWith('p-1')
    // The badge sits inside the row that toggles expansion. Without stopPropagation the click
    // would also collapse or expand the project the reader just decided to look into.
    //
    // Asserted on aria-expanded, NOT on the absence of a work package bar: the bar arrives from
    // an awaited fetch, so it is absent one tick after any click and that assertion stayed green
    // with stopPropagation deleted. aria-expanded flips synchronously.
    expect(screen.getByTestId('project-toggle-p-1').getAttribute('aria-expanded')).toBe('false')
  })

  it('labels the badge as AFFECTED BY conflicts, not as conflicts owned by the project', () => {
    // Not cosmetic. A conflict belongs to a RESOURCE over a period and is attributed to every
    // project whose work package is involved, so these counts do not sum to the total: measured
    // on the seeded data, 2 distinct conflicts produced 3 badged projects summing to 4. Wording
    // like "2 conflicts in this project" invites addition and makes the planner's own arithmetic
    // disagree with the dashboard. If someone "fixes" the label back, this fails.
    renderWithCounts(new Map([['p-1', 2]]))

    const badge = screen.getByTestId('project-conflicts-p-1')
    expect(badge.getAttribute('aria-label')).toBe('gantt.projectConflictsTooltip')
  })

  it('uses the singular label for exactly one conflict', () => {
    // German inflects the noun after a number — "1 Konflikt" but "2 Konflikten" — and the
    // interpolation helper has no plural rules, so the choice has to be explicit.
    renderWithCounts(new Map([['p-1', 1]]))

    expect(screen.getByTestId('project-conflicts-p-1').getAttribute('aria-label')).toBe(
      'gantt.projectConflictsTooltipOne',
    )
  })
})
