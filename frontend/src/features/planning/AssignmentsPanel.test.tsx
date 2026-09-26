/**
 * Unit tests for AssignmentsPanel.
 *
 * Validates: Requirements 1.5, 5.3, 7.2
 *
 * Tests:
 * - FilterBar renders with search input, type select, and "New Assignment" button
 * - Filtering by type shows only assignments of that type
 * - Filtering by search text filters by resource name, work package name, or project name
 * - Capacity warnings display in the modal after creating an assignment
 */

// @vitest-environment jsdom

import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'

import { createTestQueryClient } from '../../testUtils/queryClient'
import { I18nProvider } from '../../i18n'
import { AssignmentsPanel } from './AssignmentsPanel'
import type { Assignment, AssignmentWithWarnings } from '../../types/assignment'
import { getAssignments, createAssignment } from '../../api/assignments'

// --- Mocks ---

vi.mock('../../api/assignments', () => ({
  getAssignments: vi.fn(),
  createAssignment: vi.fn(),
  updateAssignment: vi.fn(),
  deleteAssignment: vi.fn(),
}))

vi.mock('./AssignmentForm', () => ({
  AssignmentForm: ({
    onSubmit,
    onCancel,
  }: {
    onSubmit: (v: unknown) => void
    onCancel: () => void
    loading?: boolean
    assignment?: unknown
  }) => (
    <div data-testid="assignment-form">
      <button
        data-testid="form-submit"
        onClick={() =>
          onSubmit({
            resource_id: 'res-1',
            resource_type: 'personal',
            work_package_id: 'wp-1',
            start_date: new Date('2025-03-01'),
            end_date: new Date('2025-03-10'),
            allocation_percent: 80,
          })
        }
      >
        Submit
      </button>
      {/* Mantine date inputs hand back `YYYY-MM-DD` / `YYYY-MM-DD HH:mm:ss` strings. */}
      <button
        data-testid="form-submit-string-dates"
        onClick={() =>
          onSubmit({
            resource_id: 'res-1',
            resource_type: 'personal',
            work_package_id: 'wp-1',
            start_date: '2025-03-01',
            end_date: '2025-03-24',
            allocation_percent: 80,
          })
        }
      >
        Submit string dates
      </button>
      <button
        data-testid="form-submit-string-timestamps"
        onClick={() =>
          onSubmit({
            resource_id: 'res-2',
            resource_type: 'infrastructure',
            work_package_id: 'wp-2',
            start_at: '2025-03-24 08:30:00',
            end_at: '2025-03-24 16:45:00',
          })
        }
      >
        Submit string timestamps
      </button>
      <button data-testid="form-cancel" onClick={onCancel}>
        Cancel
      </button>
    </div>
  ),
}))

vi.mock('@mantine/notifications', () => ({
  notifications: {
    show: vi.fn(),
  },
}))

// --- Fake Data ---

const fakeAssignments: Assignment[] = [
  {
    id: 'a1',
    resource_id: 'r1',
    resource_name: 'Resource Alpha',
    resource_type: 'personal',
    work_package_id: 'wp1',
    work_package_name: 'Package One',
    project_id: 'p1',
    project_name: 'Project Gamma',
    start_date: '2025-03-01',
    end_date: '2025-03-15',
    allocation_percent: 50,
    start_at: null,
    end_at: null,
    skill_mismatch: false,
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2025-01-01T00:00:00Z',
  },
  {
    id: 'a2',
    resource_id: 'r2',
    resource_name: 'Resource Beta',
    resource_type: 'infrastructure',
    work_package_id: 'wp2',
    work_package_name: 'Package Two',
    project_id: 'p2',
    project_name: 'Project Delta',
    start_date: null,
    end_date: null,
    allocation_percent: null,
    start_at: '2025-03-05T08:00:00Z',
    end_at: '2025-03-05T16:00:00Z',
    skill_mismatch: false,
    created_at: '2025-01-02T00:00:00Z',
    updated_at: '2025-01-02T00:00:00Z',
  },
  {
    id: 'a3',
    resource_id: 'r3',
    resource_name: 'Resource Gamma',
    resource_type: 'personal',
    work_package_id: 'wp3',
    work_package_name: 'Package Three',
    project_id: 'p1',
    project_name: 'Project Gamma',
    start_date: '2025-04-01',
    end_date: '2025-04-10',
    allocation_percent: 75,
    start_at: null,
    end_at: null,
    skill_mismatch: false,
    created_at: '2025-01-03T00:00:00Z',
    updated_at: '2025-01-03T00:00:00Z',
  },
]

// --- Setup ---

const mockedGetAssignments = vi.mocked(getAssignments)
const mockedCreateAssignment = vi.mocked(createAssignment)

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

function renderPanel() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MantineProvider>
        <I18nProvider locale="en">
          <AssignmentsPanel />
        </I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
}

// --- Tests ---

describe('AssignmentsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedGetAssignments.mockResolvedValue(fakeAssignments)
  })

  describe('FilterBar rendering (Requirement 1.5)', () => {
    it('renders a search input with correct placeholder', async () => {
      renderPanel()

      await waitFor(() => {
        expect(
          screen.getByPlaceholderText('Search by resource, package or project...'),
        ).toBeInTheDocument()
      })
    })

    it('renders a type filter select with "All types" placeholder', async () => {
      renderPanel()

      await waitFor(() => {
        expect(screen.getByPlaceholderText('All types')).toBeInTheDocument()
      })
    })

    it('renders a "New Assignment" button', async () => {
      renderPanel()

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /New Assignment/i })).toBeInTheDocument()
      })
    })
  })

  describe('Filtering by type (Requirement 5.3)', () => {
    it('shows all assignments when no type filter is selected', async () => {
      renderPanel()

      await waitFor(() => {
        expect(screen.getByText('Resource Alpha')).toBeInTheDocument()
        expect(screen.getByText('Resource Beta')).toBeInTheDocument()
        expect(screen.getByText('Resource Gamma')).toBeInTheDocument()
      })
    })

    it('shows only personal assignments when personal type is selected', async () => {
      renderPanel()

      await waitFor(() => {
        expect(screen.getByText('Resource Alpha')).toBeInTheDocument()
      })

      // Click the type filter select to open dropdown
      const typeSelect = screen.getByPlaceholderText('All types')
      fireEvent.click(typeSelect)

      // Mantine Select renders hidden options; use hidden: true to find them
      const personnelOption = await screen.findByRole('option', {
        name: 'People',
        hidden: true,
      })
      fireEvent.click(personnelOption)

      // Only personal assignments should be visible
      await waitFor(() => {
        expect(screen.getByText('Resource Alpha')).toBeInTheDocument()
        expect(screen.getByText('Resource Gamma')).toBeInTheDocument()
        expect(screen.queryByText('Resource Beta')).not.toBeInTheDocument()
      })
    })

    it('shows only infrastructure assignments when infrastructure type is selected', async () => {
      renderPanel()

      await waitFor(() => {
        expect(screen.getByText('Resource Beta')).toBeInTheDocument()
      })

      // Click the type filter select to open dropdown
      const typeSelect = screen.getByPlaceholderText('All types')
      fireEvent.click(typeSelect)

      // Mantine Select renders hidden options; use hidden: true to find them
      const infraOption = await screen.findByRole('option', {
        name: 'Infrastructure',
        hidden: true,
      })
      fireEvent.click(infraOption)

      await waitFor(() => {
        expect(screen.getByText('Resource Beta')).toBeInTheDocument()
        expect(screen.queryByText('Resource Alpha')).not.toBeInTheDocument()
        expect(screen.queryByText('Resource Gamma')).not.toBeInTheDocument()
      })
    })
  })

  describe('Filtering by search text (Requirement 5.3)', () => {
    it('filters by resource name', async () => {
      renderPanel()

      await waitFor(() => {
        expect(screen.getByText('Resource Alpha')).toBeInTheDocument()
      })

      const searchInput = screen.getByPlaceholderText('Search by resource, package or project...')
      fireEvent.change(searchInput, { target: { value: 'Alpha' } })

      await waitFor(() => {
        expect(screen.getByText('Resource Alpha')).toBeInTheDocument()
        expect(screen.queryByText('Resource Beta')).not.toBeInTheDocument()
        expect(screen.queryByText('Resource Gamma')).not.toBeInTheDocument()
      })
    })

    it('filters by work package name', async () => {
      renderPanel()

      await waitFor(() => {
        expect(screen.getByText('Package One')).toBeInTheDocument()
      })

      const searchInput = screen.getByPlaceholderText('Search by resource, package or project...')
      fireEvent.change(searchInput, { target: { value: 'Package Two' } })

      await waitFor(() => {
        expect(screen.getByText('Package Two')).toBeInTheDocument()
        expect(screen.queryByText('Package One')).not.toBeInTheDocument()
        expect(screen.queryByText('Package Three')).not.toBeInTheDocument()
      })
    })

    it('filters by project name', async () => {
      renderPanel()

      await waitFor(() => {
        expect(screen.getByText('Resource Alpha')).toBeInTheDocument()
      })

      const searchInput = screen.getByPlaceholderText('Search by resource, package or project...')
      fireEvent.change(searchInput, { target: { value: 'Delta' } })

      await waitFor(() => {
        expect(screen.getByText('Resource Beta')).toBeInTheDocument()
        expect(screen.queryByText('Resource Alpha')).not.toBeInTheDocument()
        expect(screen.queryByText('Resource Gamma')).not.toBeInTheDocument()
      })
    })
  })

  describe('Submitting Mantine string date values', () => {
    /** Open the create modal and wait for the (stubbed) form. */
    async function openCreateModal() {
      renderPanel()
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /New Assignment/i })).toBeInTheDocument()
      })
      fireEvent.click(screen.getByRole('button', { name: /New Assignment/i }))
      await waitFor(() => {
        expect(screen.getByTestId('assignment-form')).toBeInTheDocument()
      })
    }

    it('converts personal date strings into ISO dates', async () => {
      mockedCreateAssignment.mockResolvedValue({
        assignment: fakeAssignments[0],
        warnings: [],
      })

      await openCreateModal()
      fireEvent.click(screen.getByTestId('form-submit-string-dates'))

      await waitFor(() => expect(mockedCreateAssignment).toHaveBeenCalledTimes(1))
      expect(mockedCreateAssignment).toHaveBeenCalledWith({
        resource_id: 'res-1',
        resource_type: 'personal',
        work_package_id: 'wp-1',
        start_date: '2025-03-01',
        end_date: '2025-03-24',
        allocation_percent: 80,
      })
    })

    it('converts infrastructure timestamp strings into ISO datetimes', async () => {
      mockedCreateAssignment.mockResolvedValue({
        assignment: fakeAssignments[1],
        warnings: [],
      })

      await openCreateModal()
      fireEvent.click(screen.getByTestId('form-submit-string-timestamps'))

      await waitFor(() => expect(mockedCreateAssignment).toHaveBeenCalledTimes(1))
      expect(mockedCreateAssignment).toHaveBeenCalledWith({
        resource_id: 'res-2',
        resource_type: 'infrastructure',
        work_package_id: 'wp-2',
        start_at: '2025-03-24T07:30:00.000Z',
        end_at: '2025-03-24T15:45:00.000Z',
      })
    })
  })

  describe('Capacity warnings in modal (Requirement 7.2)', () => {
    it('displays capacity warning alert when assignment creation returns warnings', async () => {
      const warningResponse: AssignmentWithWarnings = {
        assignment: fakeAssignments[0],
        warnings: ['Resource Alpha exceeds 100% allocation on 2025-03-05'],
      }
      mockedCreateAssignment.mockResolvedValue(warningResponse)

      renderPanel()

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /New Assignment/i })).toBeInTheDocument()
      })

      // Open the create modal
      fireEvent.click(screen.getByRole('button', { name: /New Assignment/i }))

      await waitFor(() => {
        expect(screen.getByTestId('assignment-form')).toBeInTheDocument()
      })

      // Submit the form (triggers createAssignment with warnings)
      fireEvent.click(screen.getByTestId('form-submit'))

      // Capacity warning should be displayed
      await waitFor(() => {
        expect(screen.getByText('Capacity Warning')).toBeInTheDocument()
        expect(
          screen.getByText('Resource Alpha exceeds 100% allocation on 2025-03-05'),
        ).toBeInTheDocument()
        expect(
          screen.getByText('The assignment was saved anyway. You can close the form.'),
        ).toBeInTheDocument()
      })
    })
  })
})
