/**
 * Writing the plan: the most consequential mutation in the product, and what it declares untrue.
 *
 * An assignment decides whether a resource is overbooked (conflicts), whether a requirement is covered
 * (the digest and the planning figures), and what all three Gantt perspectives draw. None of that is on
 * the screen that made the change, and the hand-written versions reloaded their own table — or, in the
 * conflict card's case, called an `onChanged()` callback and left it to whichever parent had rendered it
 * to decide what to refresh.
 *
 * ONE ASYMMETRY IS PINNED HERE ON PURPOSE. Capacity is NOT invalidated: an assignment CONSUMES capacity,
 * it does not change how much there is. The relationship only runs one way, and invalidating it anyway
 * would refetch profiles and holidays on every assignment for nothing. That is the sort of thing that
 * gets added later "to be safe", so a test says it should not be.
 */
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/assignments', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/assignments')>()),
  getAssignments: vi.fn(),
  createAssignment: vi.fn(),
  updateAssignment: vi.fn(),
  deleteAssignment: vi.fn(),
  getPlanningOverview: vi.fn(),
}))

const showErrorNotification = vi.fn()
vi.mock('../../utils/errorHandling', () => ({
  showErrorNotification: (...args: unknown[]) => showErrorNotification(...args),
}))

vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}))

import { deleteAssignment, getAssignments } from '../../api/assignments'
import type { Assignment } from '../../types/assignment'
import { queryKeys } from '../../api/queryClient'
import { createTestQueryClient, trackInvalidations } from '../../testUtils/queryClient'
import { I18nProvider } from '../../i18n'
import { AssignmentsPanel } from './AssignmentsPanel'

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

function assignment(id: string): Assignment {
  return {
    id,
    resource_id: 'r1',
    resource_name: 'A. Beispiel',
    resource_type: 'personal',
    work_package_id: 'wp1',
    work_package_name: 'Demontage',
    project_id: 'p1',
    project_name: 'Baureihe 4T',
    start_date: '2026-09-01',
    end_date: '2026-09-05',
    allocation_percent: 100,
    start_at: null,
    end_at: null,
  } as unknown as Assignment
}

function renderPanel() {
  const client = createTestQueryClient()
  const invalidated = trackInvalidations(client)
  const view = render(
    <QueryClientProvider client={client}>
      <MantineProvider>
        <I18nProvider locale="de">
          <AssignmentsPanel />
        </I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
  return { ...view, invalidated }
}

describe('AssignmentsPanel plan changes', () => {
  beforeEach(() => {
    vi.mocked(getAssignments).mockReset()
    vi.mocked(deleteAssignment).mockReset()
    showErrorNotification.mockReset()
  })

  it('declares the whole plan untrue when an assignment is deleted', async () => {
    vi.mocked(getAssignments).mockResolvedValue([assignment('a1')])
    vi.mocked(deleteAssignment).mockResolvedValue(undefined)

    const { invalidated } = renderPanel()
    await waitFor(() => expect(screen.getByTestId('assignment-delete-a1')).toBeTruthy())

    fireEvent.click(screen.getByTestId('assignment-delete-a1'))
    // The row's delete opens a confirmation; confirm it.
    await waitFor(() => expect(screen.getByTestId('assignment-delete-confirm')).toBeTruthy())
    fireEvent.click(screen.getByTestId('assignment-delete-confirm'))

    await waitFor(() => expect(deleteAssignment).toHaveBeenCalledWith('a1'))
    await waitFor(() => {
      for (const key of [
        queryKeys.assignments.all,
        queryKeys.conflicts.all,
        queryKeys.planning.all,
        queryKeys.digest.all,
        queryKeys.resources.all,
      ]) {
        expect(invalidated).toContainEqual([...key])
      }
    })
  })

  it('does NOT invalidate capacity, because an assignment consumes it rather than changing it', async () => {
    // The relationship runs one way. Adding this invalidation "to be safe" would refetch profiles and
    // holidays on every assignment, so its absence is asserted.
    vi.mocked(getAssignments).mockResolvedValue([assignment('a1')])
    vi.mocked(deleteAssignment).mockResolvedValue(undefined)

    const { invalidated } = renderPanel()
    await waitFor(() => expect(screen.getByTestId('assignment-delete-a1')).toBeTruthy())
    fireEvent.click(screen.getByTestId('assignment-delete-a1'))
    await waitFor(() => expect(screen.getByTestId('assignment-delete-confirm')).toBeTruthy())
    fireEvent.click(screen.getByTestId('assignment-delete-confirm'))

    await waitFor(() => expect(deleteAssignment).toHaveBeenCalled())
    expect(invalidated).not.toContainEqual([...queryKeys.capacity.all])
  })

  it('invalidates nothing when the delete fails', async () => {
    vi.mocked(getAssignments).mockResolvedValue([assignment('a1')])
    vi.mocked(deleteAssignment).mockRejectedValue(new Error('boom'))

    const { invalidated } = renderPanel()
    await waitFor(() => expect(screen.getByTestId('assignment-delete-a1')).toBeTruthy())
    fireEvent.click(screen.getByTestId('assignment-delete-a1'))
    await waitFor(() => expect(screen.getByTestId('assignment-delete-confirm')).toBeTruthy())
    fireEvent.click(screen.getByTestId('assignment-delete-confirm'))

    await waitFor(() => expect(showErrorNotification).toHaveBeenCalledTimes(1))
    expect(invalidated).toEqual([])
  })
})
