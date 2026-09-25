// @vitest-environment jsdom

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { createTestQueryClient } from '../../testUtils/queryClient'

vi.mock('../conflicts/ConflictCheckStatus', () => ({ ConflictCheckStatus: () => null }))
vi.mock('../../api/projects', () => ({ getProjects: vi.fn() }))
vi.mock('../../api/projectOverview', () => ({ getProjectOverview: vi.fn() }))
vi.mock('../../api/resources', () => ({ getGroups: vi.fn() }))
vi.mock('../../api/ganttResources', () => ({
  getInfraGroupGanttData: vi.fn(),
  getDepartmentGanttData: vi.fn(),
}))
vi.mock('./projectGantt/ProjectsOverviewChart', () => ({
  ProjectsOverviewChart: ({
    onConflictClick,
    onProjectConflictClick,
  }: {
    onConflictClick: (bar: { id: string }) => void
    onProjectConflictClick: (projectId: string) => void
  }) => (
    <div>
      <button onClick={() => onConflictClick({ id: 'painting' })}>Painting conflict</button>
      <button onClick={() => onProjectConflictClick('project-1')}>Project conflicts</button>
    </div>
  ),
}))

import { getProjects } from '../../api/projects'
import { getProjectOverview } from '../../api/projectOverview'
import { GanttSection } from './GanttSection'

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  })
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

beforeEach(() => {
  vi.mocked(getProjects).mockResolvedValue([])
  vi.mocked(getProjectOverview).mockResolvedValue({ projects: [] })
})

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname + location.search}</div>
}

function renderGantt() {
  return render(
    <MemoryRouter initialEntries={['/gantt']}>
      <QueryClientProvider client={createTestQueryClient()}>
        <MantineProvider env="test">
          <GanttSection />
          <LocationProbe />
        </MantineProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('Gantt conflict navigation', () => {
  it('keeps the work package when opening planning', async () => {
    renderGantt()

    fireEvent.click(await screen.findByRole('button', { name: 'Painting conflict' }))

    expect(screen.getByTestId('location')).toHaveTextContent('/planning?work_package=painting')
  })

  it('keeps the project when opening a collapsed project’s conflict badge', async () => {
    renderGantt()

    fireEvent.click(await screen.findByRole('button', { name: 'Project conflicts' }))

    expect(screen.getByTestId('location')).toHaveTextContent('/planning?project=project-1')
  })
})
