/**
 * Regression tests for editing a work package's time range.
 *
 * Covers two defects that made saving a changed time range fail:
 *
 * 1. Mantine's date inputs emit `YYYY-MM-DD` **strings** from `onChange`, not
 *    `Date` objects. The form stored those strings in state typed as `Date`, so
 *    submitting crashed inside `toIsoDate` (`value.getFullYear is not a
 *    function`) and surfaced as a generic error notification — no request ever
 *    reached the backend.
 * 2. dayjs ran without the `customParseFormat` plugin, so typed `DD.MM.YYYY`
 *    input was parsed by `new Date(...)`: `06.04.2026` became June 4th and
 *    `24.04.2026` was discarded while the input still showed the typed text.
 *
 * The tests deliberately use a day-of-month above 12 for one date so a
 * month/day swap cannot pass unnoticed, drive the real `WorkPackageForm`
 * (not a stub), and assert on the rendered modal plus the API payload.
 */

// @vitest-environment jsdom

import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'

import { createTestQueryClient } from '../../testUtils/queryClient'
import { I18nProvider } from '../../i18n'
import type { Project } from '../../types/project'
import type { WorkPackage } from '../../types/workPackage'

// --- Fixtures (fictional data only) ---

const mockProject: Project = {
  id: 'project-1',
  name: 'Test Project A',
  folder_id: null,
  position: 0,
  external_ref: null,
  committed_delivery_date: null,
  customer_id: null,
  customer_name: null,
  customer_inherited: false,
  priority: 'normal' as const,
  start_date: '2026-01-01',
  end_date: '2026-12-31',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const mockWorkPackage: WorkPackage = {
  id: 'wp-1',
  project_id: 'project-1',
  name: 'Work Package One',
  lead_time_working_days: null,
  completed_at: null,
  start_date: '2026-03-02',
  end_date: '2026-03-20',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

// --- Mocks ---

vi.mock('../../api/workPackages', () => ({
  getWorkPackages: vi.fn(),
  createWorkPackage: vi.fn(),
  updateWorkPackage: vi.fn(),
  deleteWorkPackage: vi.fn(),
  copyRequirementsFromTemplate: vi.fn(),
  getWorkPackageRequirements: vi.fn(),
  addWorkPackageRequirement: vi.fn(),
  removeWorkPackageRequirement: vi.fn(),
}))

vi.mock('../../api/templates', () => ({
  getTemplates: vi.fn(),
}))

vi.mock('../../components/RequirementsEditor', () => ({
  RequirementsEditor: () => <div data-testid="requirements-editor" />,
}))

vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}))

import {
  getWorkPackages,
  getWorkPackageRequirements,
  updateWorkPackage,
} from '../../api/workPackages'
import { getTemplates } from '../../api/templates'
import { notifications } from '@mantine/notifications'
import { WorkPackagesSection } from './WorkPackagesSection'

const mockedGetWorkPackages = vi.mocked(getWorkPackages)
const mockedGetRequirements = vi.mocked(getWorkPackageRequirements)
const mockedUpdateWorkPackage = vi.mocked(updateWorkPackage)
const mockedGetTemplates = vi.mocked(getTemplates)
const mockedNotificationsShow = vi.mocked(notifications.show)

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

  // Mantine's ScrollArea (used by the date picker dropdown) needs ResizeObserver.
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

function renderSection() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MantineProvider>
        <I18nProvider locale="en">
          <WorkPackagesSection project={mockProject} onBack={vi.fn()} />
        </I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
}

/** Open the edit modal for the seeded work package and wait for its inputs. */
async function openEditModal() {
  renderSection()
  await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument())
  fireEvent.click(screen.getByLabelText('Edit work package'))
  await waitFor(() => expect(screen.getByLabelText(/^Start Date/)).toBeInTheDocument())
}

describe('WorkPackagesSection — editing the time range', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedGetWorkPackages.mockResolvedValue([mockWorkPackage])
    mockedGetRequirements.mockResolvedValue([])
    mockedGetTemplates.mockResolvedValue([])
    mockedUpdateWorkPackage.mockResolvedValue({
      work_package: mockWorkPackage,
      warnings: [],
    })
  })

  it('prefills the modal date inputs with the stored time range', async () => {
    await openEditModal()

    expect(screen.getByLabelText(/^Start Date/)).toHaveValue('02.03.2026')
    expect(screen.getByLabelText(/^End Date/)).toHaveValue('20.03.2026')
    expect(screen.getByLabelText(/^Name/)).toHaveValue('Work Package One')
  })

  it('sends the changed time range as ISO dates instead of failing', async () => {
    await openEditModal()

    fireEvent.change(screen.getByLabelText(/^Start Date/), { target: { value: '06.04.2026' } })
    fireEvent.change(screen.getByLabelText(/^End Date/), { target: { value: '24.04.2026' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mockedUpdateWorkPackage).toHaveBeenCalledTimes(1))
    expect(mockedUpdateWorkPackage).toHaveBeenCalledWith('project-1', 'wp-1', {
      name: 'Work Package One',
      start_date: '2026-04-06',
      end_date: '2026-04-24',
      // Sent as null, not omitted: the fixture claims no lead time, and null is the
      // single representation of "no claim".
      lead_time_working_days: null,
    })

    // No error notification: the old crash surfaced as a red "unexpected error".
    const shownMessages = mockedNotificationsShow.mock.calls.map((call) => call[0])
    expect(shownMessages.some((n) => n.color === 'red')).toBe(false)
    expect(shownMessages.some((n) => n.message === 'Work package has been updated.')).toBe(true)
  })

  it('keeps the stored time range when only the name is edited', async () => {
    await openEditModal()

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Work Package Renamed' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mockedUpdateWorkPackage).toHaveBeenCalledTimes(1))
    expect(mockedUpdateWorkPackage).toHaveBeenCalledWith('project-1', 'wp-1', {
      name: 'Work Package Renamed',
      start_date: '2026-03-02',
      end_date: '2026-03-20',
      lead_time_working_days: null,
    })
  })

  it('rejects an end date before the start date and does not call the API', async () => {
    await openEditModal()

    fireEvent.change(screen.getByLabelText(/^End Date/), { target: { value: '01.03.2026' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(screen.getByText('End date must be after start date')).toBeInTheDocument(),
    )
    expect(mockedUpdateWorkPackage).not.toHaveBeenCalled()
  })

  it('renders backend warnings in the modal and keeps it open', async () => {
    mockedUpdateWorkPackage.mockResolvedValue({
      work_package: mockWorkPackage,
      warnings: ['The work package end date is after the project end date (2026-12-31).'],
    })

    await openEditModal()

    fireEvent.change(screen.getByLabelText(/^End Date/), { target: { value: '15.01.2027' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(
        screen.getByText('The work package end date is after the project end date (2026-12-31).'),
      ).toBeInTheDocument(),
    )
    expect(screen.getByLabelText(/^End Date/)).toBeInTheDocument()
  })
})
