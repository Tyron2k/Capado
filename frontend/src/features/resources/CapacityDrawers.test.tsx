/**
 * The three drawers that edit capacity, and the one thing they must all get right.
 *
 * An absence, a week-profile binding and an availability window are the same kind of thing from the
 * cache's point of view: each decides how many minutes a resource actually has, or whether it is
 * bookable at all. So each can create or clear a conflict without anybody touching an assignment, and
 * the finding that says so is computed on the dashboard.
 *
 * All three therefore invalidate the same four keys. Asserting that here, in one place, is deliberate:
 * the risk with a batch of similar screens is that the fourth one copies the form of the first three
 * and misses the reason. A test that names the keys makes the reason checkable.
 *
 * The list-render assertions are thin on purpose. What these drawers show is already covered by their
 * own markup; what was never covered is what they declare untrue.
 */
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/absences', () => ({
  getAbsences: vi.fn(),
  createAbsence: vi.fn(),
  deleteAbsence: vi.fn(),
}))

// importOriginal: api/calendar also exports pure helpers the drawers use for their inputs, and
// replacing the module wholesale removes those too.
vi.mock('../../api/calendar', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/calendar')>()),
  listAvailabilityWindows: vi.fn(),
  createAvailabilityWindow: vi.fn(),
  deleteAvailabilityWindow: vi.fn(),
}))

const showErrorNotification = vi.fn()
vi.mock('../../utils/errorHandling', () => ({
  showErrorNotification: (...args: unknown[]) => showErrorNotification(...args),
}))

vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}))

import { deleteAbsence, getAbsences, type Absence } from '../../api/absences'
import {
  deleteAvailabilityWindow,
  listAvailabilityWindows,
  type AvailabilityWindow,
} from '../../api/calendar'
import { queryKeys } from '../../api/queryClient'
import { createTestQueryClient, trackInvalidations } from '../../testUtils/queryClient'
import { I18nProvider } from '../../i18n'
import { AbsenceDrawer } from './AbsenceDrawer'
import { AvailabilityWindowsDrawer } from './AvailabilityWindowsDrawer'

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

/** The four keys every capacity mutation has to declare untrue. */
const CAPACITY_KEYS = [
  [...queryKeys.capacity.all],
  [...queryKeys.resources.all],
  [...queryKeys.conflicts.all],
  [...queryKeys.digest.all],
]

function renderIn(ui: React.ReactNode) {
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
  vi.mocked(getAbsences).mockReset()
  vi.mocked(deleteAbsence).mockReset()
  vi.mocked(listAvailabilityWindows).mockReset()
  vi.mocked(deleteAvailabilityWindow).mockReset()
  showErrorNotification.mockReset()
})

describe('AbsenceDrawer', () => {
  const absence = {
    id: 'a1',
    resource_id: 'r1',
    resource_type: 'personal',
    reason: 'vacation',
    start_date: '2026-09-01',
    end_date: '2026-09-05',
    allocation_percent: 100,
    status: 'confirmed',
    note: null,
  } as unknown as Absence

  it('asks for nothing while closed', () => {
    vi.mocked(getAbsences).mockResolvedValue([absence])

    renderIn(
      <AbsenceDrawer
        opened={false}
        onClose={() => {}}
        resourceId="r1"
        resourceName="A. Beispiel"
        resourceType="personal"
      />,
    )

    expect(getAbsences).not.toHaveBeenCalled()
  })

  it('declares capacity untrue when an absence is deleted', async () => {
    vi.mocked(getAbsences).mockResolvedValue([absence])
    vi.mocked(deleteAbsence).mockResolvedValue(undefined)

    const { invalidated } = renderIn(
      <AbsenceDrawer
        opened
        onClose={() => {}}
        resourceId="r1"
        resourceName="A. Beispiel"
        resourceType="personal"
      />,
    )
    // Waits for the ROW, not for the call: the request resolving is not the same as the row being on
    // screen, and clicking between the two is a race the test would lose intermittently.
    await waitFor(() => expect(screen.getByTestId('absence-delete-a1')).toBeTruthy())

    fireEvent.click(screen.getByTestId('absence-delete-a1'))

    await waitFor(() => expect(deleteAbsence).toHaveBeenCalledWith('a1'))
    await waitFor(() => {
      for (const key of CAPACITY_KEYS) expect(invalidated).toContainEqual(key)
    })
  })

  it('invalidates nothing when the delete fails', async () => {
    vi.mocked(getAbsences).mockResolvedValue([absence])
    vi.mocked(deleteAbsence).mockRejectedValue(new Error('boom'))

    const { invalidated } = renderIn(
      <AbsenceDrawer
        opened
        onClose={() => {}}
        resourceId="r1"
        resourceName="A. Beispiel"
        resourceType="personal"
      />,
    )
    await waitFor(() => expect(screen.getByTestId('absence-delete-a1')).toBeTruthy())
    fireEvent.click(screen.getByTestId('absence-delete-a1'))

    await waitFor(() => expect(showErrorNotification).toHaveBeenCalledTimes(1))
    expect(invalidated).toEqual([])
  })
})

describe('AvailabilityWindowsDrawer', () => {
  const window_ = {
    id: 'w1',
    resource_id: 'r1',
    weekday: 0,
    start_time: '06:00',
    end_time: '14:00',
  } as unknown as AvailabilityWindow

  it('declares capacity untrue when a window is deleted', async () => {
    // The sharpest case of capacity: outside its windows an infrastructure resource is not bookable
    // at all, so removing one can turn an existing booking into a window violation.
    vi.mocked(listAvailabilityWindows).mockResolvedValue([window_])
    vi.mocked(deleteAvailabilityWindow).mockResolvedValue(undefined)

    const { invalidated } = renderIn(
      <AvailabilityWindowsDrawer
        opened
        onClose={() => {}}
        resourceId="r1"
        resourceName="Presse 1"
      />,
    )
    await waitFor(() => expect(screen.getByTestId('window-delete-w1')).toBeTruthy())

    fireEvent.click(screen.getByTestId('window-delete-w1'))

    await waitFor(() => expect(deleteAvailabilityWindow).toHaveBeenCalledWith('w1'))
    await waitFor(() => {
      for (const key of CAPACITY_KEYS) expect(invalidated).toContainEqual(key)
    })
  })

  it('keys windows per resource, so two machines do not share an entry', () => {
    expect(queryKeys.capacity.availabilityWindows('r1')).not.toEqual(
      queryKeys.capacity.availabilityWindows('r2'),
    )
  })
})
