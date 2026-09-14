/**
 * PROJECT MASTER DATA VERSUS PLAN DATA — the distinction this batch exists to draw.
 *
 * Both live in the projects feature and look alike on screen. A project's name, folder, customer and
 * reference are labels and structure: nothing about how much work is committed to whom changes when
 * they do. A work package's dates and its requirements are commitments: assignments hang off them, the
 * critical path is computed from them, and the digest reports on them.
 *
 * So a project write invalidates `projects` and stops, while a work-package write invalidates five
 * keys. Getting this backwards is not visibly broken either way — over-invalidating just costs
 * requests, under-invalidating just shows a stale number — which is exactly why it needs a test rather
 * than a convention.
 *
 * The work-package case also pins a REAL BUG THIS BATCH FIXED: every write reloaded the work packages
 * and nothing else, so moving a package's end date left the float column beside it showing slack
 * computed from the old date. Both live under the coarse `projects` prefix now, so they cannot disagree.
 */
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/projects', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/projects')>()),
  getProjects: vi.fn(),
  getProjectFolders: vi.fn(),
  getProjectSchedule: vi.fn(),
  deleteProject: vi.fn(),
}))

vi.mock('../../api/workPackages', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/workPackages')>()),
  getWorkPackages: vi.fn(),
  deleteWorkPackage: vi.fn(),
}))

const showErrorNotification = vi.fn()
vi.mock('../../utils/errorHandling', () => ({
  showErrorNotification: (...args: unknown[]) => showErrorNotification(...args),
}))

vi.mock('@mantine/notifications', () => ({ notifications: { show: vi.fn() } }))

vi.mock('../../hooks/usePermissions', () => ({
  usePermissions: () => ({
    canWrite: true,
    canRead: true,
    isAdmin: true,
    canEditProject: () => true,
    canDeleteProject: () => true,
  }),
}))

import {
  deleteProject,
  getProjectFolders,
  getProjects,
  getProjectSchedule,
} from '../../api/projects'
import { deleteWorkPackage, getWorkPackages } from '../../api/workPackages'
import { queryKeys } from '../../api/queryClient'
import { createTestQueryClient, trackInvalidations } from '../../testUtils/queryClient'
import { I18nProvider } from '../../i18n'
import { ProjectsPanel } from './ProjectsPanel'
import { WorkPackagesSection } from './WorkPackagesSection'
import type { Project } from '../../types/project'

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
  window.confirm = vi.fn(() => true)
})

const project = {
  id: 'p1',
  name: 'Baureihe 4T',
  start_date: '2026-09-01',
  end_date: '2026-12-01',
  folder_id: null,
  position: 0,
  external_ref: null,
  committed_delivery_date: null,
  customer_id: null,
  priority: 1,
} as unknown as Project

function renderWith(ui: React.ReactElement) {
  const client = createTestQueryClient()
  const invalidated = trackInvalidations(client)
  const view = render(
    <QueryClientProvider client={client}>
      <MantineProvider>
        <I18nProvider locale="de">{ui}</I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
  return { ...view, invalidated }
}

beforeEach(() => {
  vi.mocked(getProjects).mockResolvedValue([project])
  vi.mocked(getProjectFolders).mockResolvedValue([])
  vi.mocked(getProjectSchedule).mockResolvedValue({ nodes: [] } as never)
  vi.mocked(getWorkPackages).mockResolvedValue([])
  showErrorNotification.mockReset()
})

describe('project master data', () => {
  it('invalidates projects and NOTHING about the plan', async () => {
    vi.mocked(deleteProject).mockResolvedValue(undefined)

    const { invalidated } = renderWith(<ProjectsPanel />)
    await waitFor(() => expect(screen.getByTestId('project-delete-p1')).toBeTruthy())

    fireEvent.click(screen.getByTestId('project-delete-p1'))
    await waitFor(() => expect(screen.getByTestId('project-delete-confirm')).toBeTruthy())
    fireEvent.click(screen.getByTestId('project-delete-confirm'))

    await waitFor(() => expect(deleteProject).toHaveBeenCalledWith('p1'))
    await waitFor(() => expect(invalidated).toContainEqual([...queryKeys.projects.all]))

    // A project is a label and a container. Nothing about the plan changed, so nothing plan-shaped is
    // declared untrue -- if this list grows, somebody widened the invalidation without a reason.
    for (const key of [
      queryKeys.assignments.all,
      queryKeys.conflicts.all,
      queryKeys.planning.all,
      queryKeys.digest.all,
      queryKeys.capacity.all,
    ]) {
      expect(invalidated).not.toContainEqual([...key])
    }
  })

  it('invalidates nothing when the project delete fails', async () => {
    vi.mocked(deleteProject).mockRejectedValue(new Error('boom'))

    const { invalidated } = renderWith(<ProjectsPanel />)
    await waitFor(() => expect(screen.getByTestId('project-delete-p1')).toBeTruthy())
    fireEvent.click(screen.getByTestId('project-delete-p1'))
    await waitFor(() => expect(screen.getByTestId('project-delete-confirm')).toBeTruthy())
    fireEvent.click(screen.getByTestId('project-delete-confirm'))

    await waitFor(() => expect(showErrorNotification).toHaveBeenCalledTimes(1))
    expect(invalidated).toEqual([])
  })
})

describe('work package data', () => {
  it('declares the plan untrue, and the derived schedule with it', async () => {
    vi.mocked(getWorkPackages).mockResolvedValue([
      {
        id: 'wp1',
        name: 'Demontage',
        start_date: '2026-09-01',
        end_date: '2026-09-10',
        lead_time_working_days: null,
        completed_at: null,
      },
    ] as never)
    vi.mocked(deleteWorkPackage).mockResolvedValue(undefined as never)

    const { invalidated } = renderWith(<WorkPackagesSection project={project} onBack={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('wp-delete-wp1')).toBeTruthy())

    fireEvent.click(screen.getByTestId('wp-delete-wp1'))
    await waitFor(() => expect(screen.getByTestId('wp-delete-confirm')).toBeTruthy())
    fireEvent.click(screen.getByTestId('wp-delete-confirm'))

    await waitFor(() => expect(deleteWorkPackage).toHaveBeenCalledWith('p1', 'wp1'))
    await waitFor(() => {
      for (const key of [
        // Covers the list AND the schedule the float column is computed from -- the staleness this
        // batch fixed. One coarse prefix, so they cannot fall out of step again.
        queryKeys.projects.all,
        queryKeys.assignments.all,
        queryKeys.conflicts.all,
        queryKeys.planning.all,
        queryKeys.digest.all,
      ]) {
        expect(invalidated).toContainEqual([...key])
      }
    })
  })

  it('does NOT invalidate capacity: a package consumes capacity rather than defining it', async () => {
    vi.mocked(getWorkPackages).mockResolvedValue([
      {
        id: 'wp1',
        name: 'Demontage',
        start_date: '2026-09-01',
        end_date: '2026-09-10',
        lead_time_working_days: null,
        completed_at: null,
      },
    ] as never)
    vi.mocked(deleteWorkPackage).mockResolvedValue(undefined as never)

    const { invalidated } = renderWith(<WorkPackagesSection project={project} onBack={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('wp-delete-wp1')).toBeTruthy())
    fireEvent.click(screen.getByTestId('wp-delete-wp1'))
    await waitFor(() => expect(screen.getByTestId('wp-delete-confirm')).toBeTruthy())
    fireEvent.click(screen.getByTestId('wp-delete-confirm'))

    await waitFor(() => expect(deleteWorkPackage).toHaveBeenCalled())
    expect(invalidated).not.toContainEqual([...queryKeys.capacity.all])
  })
})
