/**
 * Unit tests for ResourceGanttChart
 *
 * Tests:
 * - Correct rendering with mock data
 * - Project grouping with headings
 * - Color logic (red on conflict, blue otherwise)
 * - Tooltip content (via buildTooltipContent helper)
 */

// @vitest-environment jsdom

import { describe, it, expect, vi, beforeAll } from 'vitest'
import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { ResourceGanttChart, buildTooltipContent } from './ResourceGanttChart'
import type { ResourceGanttResponse } from '../../api/ganttResources'
import { I18nProvider } from '../../i18n'

// Mock window.matchMedia and ResizeObserver for Mantine
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

  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

// --- Mock Data ---

const mockData: ResourceGanttResponse = {
  resource_type: 'infrastructure',
  resource_name: 'Hall A',
  projects: [
    {
      project_id: '11111111-1111-1111-1111-111111111111',
      project_name: 'Project Alpha',
      work_packages: [
        {
          id: 'aaaa1111-1111-1111-1111-111111111111',
          name: 'Frame Assembly',
          start_date: '2025-03-01',
          end_date: '2025-03-10',
          resource_id: 'cccc1111-1111-1111-1111-111111111111',
          resource_name: 'Crane 1',
          allocation_percent: 100,
          has_conflict: false,
        },
        {
          id: 'aaaa2222-2222-2222-2222-222222222222',
          name: 'Welding Work',
          start_date: '2025-03-05',
          end_date: '2025-03-15',
          resource_id: 'cccc2222-2222-2222-2222-222222222222',
          resource_name: 'Welder 2',
          allocation_percent: 100,
          has_conflict: true,
        },
      ],
    },
    {
      project_id: '22222222-2222-2222-2222-222222222222',
      project_name: 'Project Beta',
      work_packages: [
        {
          id: 'bbbb1111-1111-1111-1111-111111111111',
          name: 'Painting',
          start_date: '2025-03-12',
          end_date: '2025-03-20',
          resource_id: 'cccc3333-3333-3333-3333-333333333333',
          resource_name: 'Paint Station',
          allocation_percent: 100,
          has_conflict: false,
        },
      ],
    },
  ],
}

// --- Helper ---

function renderWithMantine(ui: React.ReactElement) {
  return render(
    <MantineProvider>
      <I18nProvider locale="en">{ui}</I18nProvider>
    </MantineProvider>,
  )
}

// --- Tests ---

describe('ResourceGanttChart', () => {
  describe('Correct rendering with mock data', () => {
    it('renders all work packages as bars', () => {
      renderWithMantine(<ResourceGanttChart data={mockData} timeScale="week" />)

      // All work package bars should be rendered with their test IDs
      expect(screen.getByTestId('gantt-bar-aaaa1111-1111-1111-1111-111111111111')).toBeTruthy()
      expect(screen.getByTestId('gantt-bar-aaaa2222-2222-2222-2222-222222222222')).toBeTruthy()
      expect(screen.getByTestId('gantt-bar-bbbb1111-1111-1111-1111-111111111111')).toBeTruthy()
    })

    it('shows work package names in the left column', () => {
      renderWithMantine(<ResourceGanttChart data={mockData} timeScale="week" />)

      // Names appear at least once (in the label column; may also appear on the bar)
      expect(screen.getAllByText('Frame Assembly').length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText('Welding Work').length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText('Painting').length).toBeGreaterThanOrEqual(1)
    })

    it('renders the time axis headers', () => {
      renderWithMantine(<ResourceGanttChart data={mockData} timeScale="week" />)

      // The header "Work Package" should be present
      expect(screen.getByText('Work Package')).toBeTruthy()
    })
  })

  describe('Project grouping with headings', () => {
    it('shows project headings for each group', () => {
      renderWithMantine(<ResourceGanttChart data={mockData} timeScale="week" />)

      expect(screen.getByText('Project Alpha')).toBeTruthy()
      expect(screen.getByText('Project Beta')).toBeTruthy()
    })

    it('renders project headings with correct test IDs', () => {
      renderWithMantine(<ResourceGanttChart data={mockData} timeScale="week" />)

      expect(
        screen.getByTestId('project-heading-11111111-1111-1111-1111-111111111111'),
      ).toBeTruthy()
      expect(
        screen.getByTestId('project-heading-22222222-2222-2222-2222-222222222222'),
      ).toBeTruthy()
    })

    it('groups work packages under their project in correct order', () => {
      const { container } = renderWithMantine(
        <ResourceGanttChart data={mockData} timeScale="week" />,
      )

      // Verify ordering: Alpha heading comes before Beta heading in DOM
      const allTestIdElements = container.querySelectorAll('[data-testid]')
      const testIds = Array.from(allTestIdElements).map((el) => el.getAttribute('data-testid'))
      const alphaIdx = testIds.indexOf('project-heading-11111111-1111-1111-1111-111111111111')
      const betaIdx = testIds.indexOf('project-heading-22222222-2222-2222-2222-222222222222')
      expect(alphaIdx).toBeGreaterThanOrEqual(0)
      expect(betaIdx).toBeGreaterThanOrEqual(0)
      expect(alphaIdx).toBeLessThan(betaIdx)

      // Alpha's bars come before Beta's bars
      const alphaBar1Idx = testIds.indexOf('gantt-bar-aaaa1111-1111-1111-1111-111111111111')
      const betaBar1Idx = testIds.indexOf('gantt-bar-bbbb1111-1111-1111-1111-111111111111')
      expect(alphaBar1Idx).toBeLessThan(betaBar1Idx)
    })
  })

  describe('Grouping toggle', () => {
    it('starts grouped by project', () => {
      renderWithMantine(<ResourceGanttChart data={mockData} timeScale="week" />)

      expect(
        screen.getByTestId('project-heading-11111111-1111-1111-1111-111111111111'),
      ).toBeTruthy()
      expect(
        screen.queryByTestId('resource-heading-cccc1111-1111-1111-1111-111111111111'),
      ).toBeNull()
    })

    it('switches the headings to resources', () => {
      renderWithMantine(<ResourceGanttChart data={mockData} timeScale="week" />)

      fireEvent.click(screen.getByRole('radio', { name: /by resource/i }))

      // One heading per resource, and the project headings are gone — this is a different fold of
      // the same rows, not an extra level of nesting.
      expect(
        screen.getByTestId('resource-heading-cccc1111-1111-1111-1111-111111111111'),
      ).toBeTruthy()
      expect(
        screen.queryByTestId('project-heading-11111111-1111-1111-1111-111111111111'),
      ).toBeNull()
    })

    it('labels rows with the project once grouped by resource', () => {
      renderWithMantine(<ResourceGanttChart data={mockData} timeScale="week" />)

      fireEvent.click(screen.getByRole('radio', { name: /by resource/i }))

      // Grouped by resource the row IS Crane 1, so the useful label is which project occupies it.
      // The project headings are gone in this mode, so any occurrence here is a row label rather
      // than a heading. (That the work package name labels the row in the OTHER mode is already
      // covered by "shows work package names in the left column".)
      expect(screen.getAllByText('Project Alpha').length).toBeGreaterThan(0)
    })

    it('keeps every bar when the grouping changes', () => {
      renderWithMantine(<ResourceGanttChart data={mockData} timeScale="week" />)

      const before = screen.getAllByTestId(/^gantt-bar-/).length

      fireEvent.click(screen.getByRole('radio', { name: /by resource/i }))

      // Regrouping must not drop or duplicate work: both views are folds of one response.
      expect(screen.getAllByTestId(/^gantt-bar-/)).toHaveLength(before)
    })
  })

  describe('Color logic', () => {
    it('shows bars with conflict in red', () => {
      renderWithMantine(<ResourceGanttChart data={mockData} timeScale="week" />)

      const conflictBar = screen.getByTestId('gantt-bar-aaaa2222-2222-2222-2222-222222222222')
      expect(conflictBar.style.backgroundColor).toBe('var(--mantine-color-red-6)')
    })

    it('shows bars without conflict in blue', () => {
      renderWithMantine(<ResourceGanttChart data={mockData} timeScale="week" />)

      const normalBar = screen.getByTestId('gantt-bar-aaaa1111-1111-1111-1111-111111111111')
      expect(normalBar.style.backgroundColor).toBe('var(--mantine-color-blue-6)')

      const normalBar2 = screen.getByTestId('gantt-bar-bbbb1111-1111-1111-1111-111111111111')
      expect(normalBar2.style.backgroundColor).toBe('var(--mantine-color-blue-6)')
    })
  })

  describe('Tooltip content', () => {
    it('buildTooltipContent returns correct work package name', () => {
      const bar = mockData.projects[0].work_packages[0]
      const content = buildTooltipContent(bar)

      expect(content.name).toBe('Frame Assembly')
    })

    it('buildTooltipContent returns correct resource name', () => {
      const bar = mockData.projects[0].work_packages[0]
      const content = buildTooltipContent(bar)

      expect(content.resourceName).toBe('Crane 1')
    })

    it('buildTooltipContent returns correct date range', () => {
      const bar = mockData.projects[0].work_packages[0]
      const content = buildTooltipContent(bar)

      expect(content.dateRange).toBe('2025-03-01 – 2025-03-10')
    })

    it('buildTooltipContent shows conflict flag when has_conflict=true', () => {
      const conflictBar = mockData.projects[0].work_packages[1]
      const content = buildTooltipContent(conflictBar)

      expect(content.hasConflict).toBe(true)
      expect(content.name).toBe('Welding Work')
      expect(content.resourceName).toBe('Welder 2')
      expect(content.dateRange).toBe('2025-03-05 – 2025-03-15')
    })

    it('buildTooltipContent shows no conflict flag when has_conflict=false', () => {
      const normalBar = mockData.projects[0].work_packages[0]
      const content = buildTooltipContent(normalBar)

      expect(content.hasConflict).toBe(false)
    })
  })

  describe('Time scale control', () => {
    it('renders SegmentedControl when onTimeScaleChange is provided', () => {
      const onTimeScaleChange = vi.fn()
      renderWithMantine(
        <ResourceGanttChart
          data={mockData}
          timeScale="week"
          onTimeScaleChange={onTimeScaleChange}
        />,
      )

      expect(screen.getByText('Day')).toBeTruthy()
      expect(screen.getByText('Week')).toBeTruthy()
      expect(screen.getByText('Month')).toBeTruthy()
    })

    it('renders no SegmentedControl without onTimeScaleChange', () => {
      renderWithMantine(<ResourceGanttChart data={mockData} timeScale="week" />)

      expect(screen.queryByText('Day')).toBeNull()
    })
  })

  describe('Empty data', () => {
    it('renders without error with empty project list', () => {
      const emptyData: ResourceGanttResponse = {
        resource_type: 'department',
        resource_name: 'Empty Department',
        projects: [],
      }

      const { container } = renderWithMantine(
        <ResourceGanttChart data={emptyData} timeScale="week" />,
      )

      // Should render without crashing
      expect(container).toBeTruthy()
      // No project headings should be present
      expect(screen.queryByTestId(/project-heading/)).toBeNull()
    })
  })

  describe('Tooltip shows allocation percent', () => {
    it('buildTooltipContent returns allocationPercent from the bar', () => {
      const bar = mockData.projects[0].work_packages[0]
      const content = buildTooltipContent(bar)
      expect(content.allocationPercent).toBe(100)
    })
  })
})
