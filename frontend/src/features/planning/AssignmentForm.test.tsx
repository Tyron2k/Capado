/**
 * Tests for the assignment form's date handling.
 *
 * Both branches (personal date range, infrastructure timestamps) seed their
 * fields from API strings and hand Mantine's string values back to the caller.
 * The infrastructure case matters because the form stores
 * `YYYY-MM-DDTHH:mm` while Mantine's `DateTimePicker` canonicalises to
 * `YYYY-MM-DD HH:mm:ss` — this test pins that round-trip instead of relying on
 * Mantine's internals staying the same.
 *
 * All fixtures are inline and fictional.
 */

// @vitest-environment jsdom

import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'

import { createTestQueryClient } from '../../testUtils/queryClient'
import { I18nProvider } from '../../i18n'
import type { Assignment } from '../../types/assignment'
import type { AssignmentFormValues } from './AssignmentForm'
import { toIsoDateTime } from '../../utils/date'

vi.mock('../../api/projects', () => ({ getProjects: vi.fn() }))
vi.mock('../../api/workPackages', () => ({ getWorkPackages: vi.fn() }))
vi.mock('../../api/assignments', () => ({ previewAssignment: vi.fn() }))

// The stub surfaces the props the form drives, so a validation error on the
// resource field stays visible instead of disappearing with the real component.
vi.mock('../../components/AutocompleteField', () => ({
  AutocompleteField: ({ value, error }: { value: string | null; error?: string }) => (
    <div data-testid="resource-field" data-value={value ?? ''} data-error={error ?? ''} />
  ),
}))

vi.mock('./SuggestionList', () => ({
  SuggestionList: () => <div data-testid="suggestion-list" />,
}))

import { getProjects } from '../../api/projects'
import { getWorkPackages } from '../../api/workPackages'
import { previewAssignment } from '../../api/assignments'
import { AssignmentForm } from './AssignmentForm'

const mockedGetProjects = vi.mocked(getProjects)
const mockedGetWorkPackages = vi.mocked(getWorkPackages)
const mockedPreviewAssignment = vi.mocked(previewAssignment)

const project = {
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
  created_at: '2026-01-01T00:00:00',
  updated_at: '2026-01-01T00:00:00',
}

const workPackage = {
  id: 'wp-1',
  project_id: 'project-1',
  name: 'Work Package One',
  lead_time_working_days: null,
  completed_at: null,
  start_date: '2026-03-02',
  end_date: '2026-03-20',
  created_at: '2026-01-01T00:00:00',
  updated_at: '2026-01-01T00:00:00',
}

const personalAssignment: Assignment = {
  id: 'assignment-1',
  resource_id: 'resource-1',
  resource_name: 'Resource One',
  resource_type: 'personal',
  work_package_id: 'wp-1',
  work_package_name: 'Work Package One',
  project_id: 'project-1',
  project_name: 'Test Project A',
  start_date: '2026-03-02',
  end_date: '2026-03-06',
  allocation_percent: 80,
  start_at: null,
  end_at: null,
  skill_mismatch: false,
  created_at: '2026-01-01T00:00:00',
  updated_at: '2026-01-01T00:00:00',
}

const infraAssignment: Assignment = {
  ...personalAssignment,
  id: 'assignment-2',
  resource_id: 'resource-2',
  resource_name: 'Station One',
  resource_type: 'infrastructure',
  start_date: null,
  end_date: null,
  allocation_percent: null,
  start_at: '2026-03-05T08:30:00',
  end_at: '2026-03-05T16:45:00',
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

/**
 * Submit the form directly.
 *
 * Clicking "Save" works for the personal branch, but not for the
 * infrastructure branch: Mantine's `DateTimePicker` renders its value as button
 * text and leaves the underlying `required` input empty, so jsdom's native
 * constraint validation refuses to submit on a click. Dispatching `submit`
 * exercises the same React handler without that artifact.
 */
function submitForm() {
  const form = screen.getByRole('button', { name: 'Save' }).closest('form')
  expect(form).not.toBeNull()
  fireEvent.submit(form as HTMLFormElement)
}

function renderForm(assignment: Assignment) {
  const onSubmit = vi.fn<(values: AssignmentFormValues) => void>()
  render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MantineProvider env="test">
        <I18nProvider locale="en">
          <AssignmentForm assignment={assignment} onSubmit={onSubmit} onCancel={vi.fn()} />
        </I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
  return { onSubmit }
}

describe('AssignmentForm — personal date range', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedGetProjects.mockResolvedValue([project])
    mockedGetWorkPackages.mockResolvedValue([workPackage])
  })

  it('prefills the date fields from the assignment', async () => {
    renderForm(personalAssignment)

    await waitFor(() => expect(screen.getByLabelText(/^Start Date/)).toHaveValue('02.03.2026'))
    expect(screen.getByLabelText(/^End Date/)).toHaveValue('06.03.2026')
  })

  it('submits typed dates as YYYY-MM-DD strings', async () => {
    const { onSubmit } = renderForm(personalAssignment)
    await waitFor(() => expect(screen.getByLabelText(/^Start Date/)).toHaveValue('02.03.2026'))

    fireEvent.change(screen.getByLabelText(/^Start Date/), { target: { value: '13.04.2026' } })
    fireEvent.change(screen.getByLabelText(/^End Date/), { target: { value: '24.04.2026' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      start_date: '2026-04-13',
      end_date: '2026-04-24',
      allocation_percent: 80,
    })
  })

  it('blocks submission when the end date precedes the start date', async () => {
    const { onSubmit } = renderForm(personalAssignment)
    await waitFor(() => expect(screen.getByLabelText(/^Start Date/)).toHaveValue('02.03.2026'))

    fireEvent.change(screen.getByLabelText(/^End Date/), { target: { value: '01.03.2026' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(screen.getByText('End date must be after start date')).toBeInTheDocument(),
    )
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('shows a read-only impact and hides it after the form changes', async () => {
    mockedPreviewAssignment.mockResolvedValue({
      resources: [
        {
          resource_id: 'resource-1',
          resource_name: 'Resource One',
          resource_type: 'personal',
          conflicts_before: [],
          conflicts_after: [
            {
              cause: 'over_allocation',
              start_date: '2026-03-02',
              end_date: '2026-03-02',
              total_assigned_percent: 120,
              available_percent: 100,
            },
          ],
          capacity_days: [
            {
              date: '2026-03-02',
              available_percent: 100,
              assigned_before_percent: 40,
              assigned_after_percent: 120,
            },
          ],
        },
      ],
    })
    const { onSubmit } = renderForm(personalAssignment)
    await waitFor(() => expect(screen.getByLabelText(/^Start Date/)).toHaveValue('02.03.2026'))

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    await waitFor(() =>
      expect(mockedPreviewAssignment).toHaveBeenCalledWith(
        expect.objectContaining({
          assignment_id: personalAssignment.id,
          resource_id: personalAssignment.resource_id,
          start_date: '2026-03-02',
        }),
      ),
    )
    expect(await screen.findByText('Conflicts: 0 → 1')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText(/^End Date/), { target: { value: '07.03.2026' } })
    await waitFor(() => expect(screen.queryByText('Conflicts: 0 → 1')).not.toBeInTheDocument())
  })
})

describe('AssignmentForm — infrastructure timestamps', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedGetProjects.mockResolvedValue([project])
    mockedGetWorkPackages.mockResolvedValue([workPackage])
  })

  it('renders the timestamps at their stored wall-clock time', async () => {
    renderForm(infraAssignment)

    // DateTimePicker renders its formatted value as button text.
    await waitFor(() =>
      expect(screen.getByLabelText(/^Occupied From/)).toHaveTextContent('05.03.2026 08:30'),
    )
    expect(screen.getByLabelText(/^Occupied Until/)).toHaveTextContent('05.03.2026 16:45')
  })

  it('submits the timestamps unchanged, minute-precise', async () => {
    const { onSubmit } = renderForm(infraAssignment)
    await waitFor(() =>
      expect(screen.getByLabelText(/^Occupied From/)).toHaveTextContent('05.03.2026 08:30'),
    )

    submitForm()

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    const values = onSubmit.mock.calls[0][0]
    expect(values.resource_type).toBe('infrastructure')
    // Mantine canonicalises to `YYYY-MM-DD HH:mm:ss`; either shape must convert
    // to the same minute-precise payload.
    expect(values.start_at).not.toBeNull()
    expect(values.end_at).not.toBeNull()
    expect(String(values.start_at)).toMatch(/^2026-03-05[T ]08:30/)
    expect(String(values.end_at)).toMatch(/^2026-03-05[T ]16:45/)
    // What the panel then sends to the API.
    expect(toIsoDateTime(values.start_at as string)).toBe('2026-03-05T08:30')
    expect(toIsoDateTime(values.end_at as string)).toBe('2026-03-05T16:45')
  })

  it('does not render the personal date fields', async () => {
    renderForm(infraAssignment)

    await waitFor(() =>
      expect(screen.getByLabelText(/^Occupied From/)).toHaveTextContent('05.03.2026 08:30'),
    )
    expect(screen.queryByLabelText(/^Start Date/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/^Allocation/)).not.toBeInTheDocument()
  })
})
