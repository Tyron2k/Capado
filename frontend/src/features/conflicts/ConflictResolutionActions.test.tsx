/**
 * Tests for the conflict resolution popover.
 *
 * The date fields here speak Mantine's string contract (`YYYY-MM-DD` /
 * `YYYY-MM-DD HH:mm:ss`). Before, the component kept `Date` objects built with
 * `new Date(isoDate)` — UTC midnight — and compared them against strings from
 * `onChange`, so range validation silently never triggered and the anchor drifted
 * a day for viewers west of UTC.
 *
 * The tests drive the real inputs, assert on rendered structure, and check the
 * payload sent to the API. All fixtures are fictional.
 */

// @vitest-environment jsdom

import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { QueryClientProvider } from '@tanstack/react-query'

import { createTestQueryClient } from '../../testUtils/queryClient'
import '@testing-library/jest-dom/vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { I18nProvider } from '../../i18n'
import type { ConflictAssignmentInfo } from '../../types/assignment'

vi.mock('../../api/assignments', () => ({
  updateAssignment: vi.fn(),
  deleteAssignment: vi.fn(),
}))

vi.mock('../../components/AutocompleteField', () => ({
  AutocompleteField: () => <div data-testid="autocomplete-field" />,
}))

vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}))

import { updateAssignment } from '../../api/assignments'
import { notifications } from '@mantine/notifications'
import { ConflictResolutionActions } from './ConflictResolutionActions'

const mockedUpdateAssignment = vi.mocked(updateAssignment)
const mockedShow = vi.mocked(notifications.show)

const personalAssignment: ConflictAssignmentInfo = {
  assignment_id: 'assignment-1',
  work_package_id: 'wp-1',
  work_package_name: 'Work Package One',
  project_id: 'project-1',
  project_name: 'Test Project A',
  resource_id: 'resource-1',
  resource_name: 'Resource One',
  start_date: '2026-03-02',
  end_date: '2026-03-06',
  allocation_percent: 80,
  start_at: null,
  end_at: null,
}

const infraAssignment: ConflictAssignmentInfo = {
  assignment_id: 'assignment-2',
  work_package_id: 'wp-2',
  work_package_name: 'Work Package Two',
  resource_id: 'resource-2',
  resource_name: 'Station One',
  start_date: null,
  end_date: null,
  allocation_percent: null,
  start_at: '2026-03-05T07:30:00Z',
  end_at: '2026-03-05T15:45:00Z',
}

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
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

function renderActions(assignment: ConflictAssignmentInfo, onChanged = vi.fn()) {
  render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MantineProvider env="test">
        <I18nProvider locale="en">
          <ConflictResolutionActions assignment={assignment} onChanged={onChanged} />
        </I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
  return { onChanged }
}

/** Open the popover and switch to the given action. */
async function openAction(name: RegExp) {
  fireEvent.click(screen.getByLabelText('Conflict actions'))
  await waitFor(() => expect(screen.getByRole('button', { name })).toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name }))
}

describe('ConflictResolutionActions — move time range (personal)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedUpdateAssignment.mockResolvedValue({
      assignment: { id: 'assignment-1' } as never,
      warnings: [],
    })
  })

  it('prefills both date fields from the assignment', async () => {
    renderActions(personalAssignment)
    await openAction(/Move Time Range/i)

    expect(screen.getByLabelText('Start')).toHaveValue('02.03.2026')
    expect(screen.getByLabelText('End')).toHaveValue('06.03.2026')
  })

  it('sends the edited range as ISO dates', async () => {
    renderActions(personalAssignment)
    await openAction(/Move Time Range/i)

    fireEvent.change(screen.getByLabelText('Start'), { target: { value: '13.04.2026' } })
    fireEvent.change(screen.getByLabelText('End'), { target: { value: '24.04.2026' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mockedUpdateAssignment).toHaveBeenCalledTimes(1))
    expect(mockedUpdateAssignment).toHaveBeenCalledWith('assignment-1', {
      start_date: '2026-04-13',
      end_date: '2026-04-24',
    })
  })

  it('rejects an end date before the start date without calling the API', async () => {
    renderActions(personalAssignment)
    await openAction(/Move Time Range/i)

    fireEvent.change(screen.getByLabelText('End'), { target: { value: '01.03.2026' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mockedShow).toHaveBeenCalled())
    expect(mockedUpdateAssignment).not.toHaveBeenCalled()
    expect(mockedShow.mock.calls.some(([n]) => n.color === 'red')).toBe(true)
  })

  it('accepts a same-day range', async () => {
    renderActions(personalAssignment)
    await openAction(/Move Time Range/i)

    fireEvent.change(screen.getByLabelText('End'), { target: { value: '02.03.2026' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mockedUpdateAssignment).toHaveBeenCalledTimes(1))
    expect(mockedUpdateAssignment).toHaveBeenCalledWith('assignment-1', {
      start_date: '2026-03-02',
      end_date: '2026-03-02',
    })
  })

  it('notifies the parent after a successful move', async () => {
    const { onChanged } = renderActions(personalAssignment)
    await openAction(/Move Time Range/i)

    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1))
  })
})

describe('ConflictResolutionActions — move time range (infrastructure)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedUpdateAssignment.mockResolvedValue({
      assignment: { id: 'assignment-2' } as never,
      warnings: [],
    })
  })

  it('prefills the timestamp fields without shifting the wall-clock time', async () => {
    renderActions(infraAssignment)
    await openAction(/Move Time Range/i)

    // DateTimePicker renders its formatted value as button text, not as a value.
    expect(screen.getByLabelText('Start')).toHaveTextContent('05.03.2026 08:30')
    expect(screen.getByLabelText('End')).toHaveTextContent('05.03.2026 16:45')
  })

  it('sends timestamps back with minute precision', async () => {
    renderActions(infraAssignment)
    await openAction(/Move Time Range/i)

    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mockedUpdateAssignment).toHaveBeenCalledTimes(1))
    expect(mockedUpdateAssignment).toHaveBeenCalledWith('assignment-2', {
      start_at: '2026-03-05T07:30:00.000Z',
      end_at: '2026-03-05T15:45:00.000Z',
    })
  })
})

describe('ConflictResolutionActions — autumn fold', () => {
  it('saves an unchanged interval whose local end precedes its local start', async () => {
    vi.clearAllMocks()
    mockedUpdateAssignment.mockResolvedValue({
      assignment: { id: 'assignment-2' } as never,
      warnings: [],
    })
    renderActions({
      ...infraAssignment,
      start_at: '2026-10-25T00:45:00Z',
      end_at: '2026-10-25T01:15:00Z',
    })
    await openAction(/Move Time Range/i)
    expect(screen.getByLabelText('Start')).toHaveTextContent('25.10.2026 02:45')
    expect(screen.getByLabelText('End')).toHaveTextContent('25.10.2026 02:15')
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(mockedUpdateAssignment).toHaveBeenCalledWith('assignment-2', {
        start_at: '2026-10-25T00:45:00.000Z',
        end_at: '2026-10-25T01:15:00.000Z',
      }),
    )
  })
})

describe('ConflictResolutionActions — available actions', () => {
  beforeEach(() => vi.clearAllMocks())

  it('offers allocation reduction only for personal assignments', async () => {
    renderActions(personalAssignment)
    fireEvent.click(screen.getByLabelText('Conflict actions'))

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Reduce Hours/i })).toBeInTheDocument(),
    )
  })

  it('hides allocation reduction for infrastructure assignments', async () => {
    renderActions(infraAssignment)
    fireEvent.click(screen.getByLabelText('Conflict actions'))

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Move Time Range/i })).toBeInTheDocument(),
    )
    expect(screen.queryByRole('button', { name: /Reduce Hours/i })).not.toBeInTheDocument()
  })
})
