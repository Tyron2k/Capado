/**
 * Unit tests for the ProjectsPanel component.
 *
 * Verifies:
 * - FilterBar renders as first content element with search input and action button
 * - DataTable receives correct loading/empty props
 * - Search filtering reduces visible rows
 * - WorkPackagesSection renders within the panel
 *
 * **Validates: Requirements 1.4, 5.1, 7.1, 7.4**
 */

// @vitest-environment jsdom

import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'

import { createTestQueryClient } from '../../testUtils/queryClient'
import type { Project } from '../../types/project'

// --- Mocks ---

const mockProjects: Project[] = [
  {
    id: '1',
    name: 'Test Project A',
    folder_id: null,
    position: 0,
    external_ref: null,
    committed_delivery_date: null,
    customer_id: null,
    customer_name: null,
    customer_inherited: false,
    priority: 'normal' as const,
    start_date: '2024-01-01',
    end_date: '2024-12-31',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: '2',
    name: 'Test Project B',
    folder_id: null,
    position: 0,
    external_ref: null,
    committed_delivery_date: null,
    customer_id: null,
    customer_name: null,
    customer_inherited: false,
    priority: 'normal' as const,
    start_date: '2024-03-01',
    end_date: '2024-09-30',
    created_at: '2024-03-01T00:00:00Z',
    updated_at: '2024-03-01T00:00:00Z',
  },
  {
    id: '3',
    name: 'Another Item',
    folder_id: null,
    position: 0,
    external_ref: null,
    committed_delivery_date: null,
    customer_id: null,
    customer_name: null,
    customer_inherited: false,
    priority: 'normal' as const,
    start_date: '2024-06-01',
    end_date: '2025-01-31',
    created_at: '2024-06-01T00:00:00Z',
    updated_at: '2024-06-01T00:00:00Z',
  },
]

vi.mock('../../api/projects', () => ({
  getProjects: vi.fn(),
  createProject: vi.fn(),
  updateProject: vi.fn(),
  deleteProject: vi.fn(),
}))

vi.mock('../../hooks/usePermissions', () => ({
  usePermissions: vi.fn(() => ({
    canWrite: true,
    canEditProject: () => true,
    isAdmin: true,
    isViewer: false,
    canEditGroup: () => true,
    canManageUsers: true,
  })),
}))

vi.mock('./WorkPackagesSection', () => ({
  WorkPackagesSection: ({ project, onBack }: { project: Project; onBack: () => void }) => (
    <div data-testid="work-packages-section">
      <span>Work Packages for {project.name}</span>
      <button onClick={onBack}>Back</button>
    </div>
  ),
}))

vi.mock('./ProjectForm', () => ({
  ProjectForm: () => <div data-testid="project-form">Project Form</div>,
}))

import { getProjects } from '../../api/projects'
import { usePermissions } from '../../hooks/usePermissions'
import { ProjectsPanel } from './ProjectsPanel'

const mockedGetProjects = vi.mocked(getProjects)
const mockedUsePermissions = vi.mocked(usePermissions)

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
})

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MantineProvider>{ui}</MantineProvider>
    </QueryClientProvider>,
  )
}

describe('ProjectsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedGetProjects.mockResolvedValue(mockProjects)
    mockedUsePermissions.mockReturnValue({
      canWrite: true,
      canEditProject: () => true,
      isAdmin: true,
      isViewer: false,
      canEditGroup: () => true,
      canManageUsers: true,
    })
  })

  describe('FilterBar rendering', () => {
    it('renders a search input with placeholder text', async () => {
      renderWithProviders(<ProjectsPanel />)

      await waitFor(() => {
        expect(screen.queryByRole('table')).toBeInTheDocument()
      })

      const searchInput = screen.getByPlaceholderText(/search/i)
      expect(searchInput).toBeInTheDocument()
      expect(searchInput.tagName).toBe('INPUT')
    })

    it('renders a "New Project" action button when user has write permission', async () => {
      renderWithProviders(<ProjectsPanel />)

      await waitFor(() => {
        expect(screen.queryByRole('table')).toBeInTheDocument()
      })

      const newButton = screen.getByRole('button', { name: /new.*project/i })
      expect(newButton).toBeInTheDocument()
    })

    it('does not render "New Project" button when user lacks write permission', async () => {
      mockedUsePermissions.mockReturnValue({
        canWrite: false,
        canEditProject: () => false,
        isAdmin: false,
        isViewer: true,
        canEditGroup: () => false,
        canManageUsers: false,
      })

      renderWithProviders(<ProjectsPanel />)

      await waitFor(() => {
        expect(screen.queryByRole('table')).toBeInTheDocument()
      })

      expect(screen.queryByRole('button', { name: /new.*project/i })).not.toBeInTheDocument()
    })
  })

  describe('DataTable loading and empty states', () => {
    it('shows loading state initially before data loads', () => {
      mockedGetProjects.mockReturnValue(new Promise(() => {})) // never resolves

      renderWithProviders(<ProjectsPanel />)

      // DataTable in loading state renders a Loader, not a table
      expect(screen.queryByRole('table')).not.toBeInTheDocument()
      expect(document.querySelector('.mantine-Loader-root')).toBeInTheDocument()
    })

    it('shows project rows after data loads', async () => {
      renderWithProviders(<ProjectsPanel />)

      await waitFor(() => {
        expect(screen.getByRole('table')).toBeInTheDocument()
      })

      expect(screen.getByText('Test Project A')).toBeInTheDocument()
      expect(screen.getByText('Test Project B')).toBeInTheDocument()
      expect(screen.getByText('Another Item')).toBeInTheDocument()
    })

    it('shows empty state when no projects exist', async () => {
      mockedGetProjects.mockResolvedValue([])

      renderWithProviders(<ProjectsPanel />)

      // Waiting for the empty MESSAGE, not for the table's absence. The absence is true while the
      // query is still pending too, so waiting on it passed instantly and then asserted the message
      // before it had rendered. Wait for what should appear.
      await waitFor(() => {
        expect(screen.queryByText(/no.*project/i)).toBeInTheDocument()
      })
      expect(screen.queryByRole('table')).not.toBeInTheDocument()
    })
  })

  describe('search filtering', () => {
    it('filters visible rows by name (case-insensitive)', async () => {
      renderWithProviders(<ProjectsPanel />)

      await waitFor(() => {
        expect(screen.getByRole('table')).toBeInTheDocument()
      })

      const searchInput = screen.getByPlaceholderText(/search/i)
      fireEvent.change(searchInput, { target: { value: 'test project' } })

      // Only the two "Test Project" items should be visible
      expect(screen.getByText('Test Project A')).toBeInTheDocument()
      expect(screen.getByText('Test Project B')).toBeInTheDocument()
      expect(screen.queryByText('Another Item')).not.toBeInTheDocument()
    })

    it('shows all rows when search is cleared', async () => {
      renderWithProviders(<ProjectsPanel />)

      await waitFor(() => {
        expect(screen.getByRole('table')).toBeInTheDocument()
      })

      const searchInput = screen.getByPlaceholderText(/search/i)

      // Filter first
      fireEvent.change(searchInput, { target: { value: 'test project' } })
      expect(screen.queryByText('Another Item')).not.toBeInTheDocument()

      // Clear filter
      fireEvent.change(searchInput, { target: { value: '' } })
      expect(screen.getByText('Another Item')).toBeInTheDocument()
      expect(screen.getByText('Test Project A')).toBeInTheDocument()
      expect(screen.getByText('Test Project B')).toBeInTheDocument()
    })

    it('search is case-insensitive', async () => {
      renderWithProviders(<ProjectsPanel />)

      await waitFor(() => {
        expect(screen.getByRole('table')).toBeInTheDocument()
      })

      const searchInput = screen.getByPlaceholderText(/search/i)
      fireEvent.change(searchInput, { target: { value: 'ANOTHER' } })

      expect(screen.getByText('Another Item')).toBeInTheDocument()
      expect(screen.queryByText('Test Project A')).not.toBeInTheDocument()
      expect(screen.queryByText('Test Project B')).not.toBeInTheDocument()
    })
  })

  describe('WorkPackagesSection', () => {
    it('renders WorkPackagesSection when a project work packages icon is clicked', async () => {
      renderWithProviders(<ProjectsPanel />)

      await waitFor(() => {
        expect(screen.getByRole('table')).toBeInTheDocument()
      })

      // Scoped to the row for this project rather than taking the first icon on the
      // page: the list is ordered by position then name, so "first row" is not a
      // stable way to address a particular project.
      const row = screen.getByText('Test Project A').closest('tr')
      expect(row).not.toBeNull()
      const wpButton = within(row as HTMLElement).getByLabelText(/work.*package/i)
      fireEvent.click(wpButton)

      // WorkPackagesSection should now be rendered
      expect(screen.getByTestId('work-packages-section')).toBeInTheDocument()
      expect(screen.getByText('Work Packages for Test Project A')).toBeInTheDocument()

      // The table should no longer be visible (panel switches to WP view)
      expect(screen.queryByRole('table')).not.toBeInTheDocument()
    })

    it('returns to project list when back is clicked in WorkPackagesSection', async () => {
      renderWithProviders(<ProjectsPanel />)

      await waitFor(() => {
        expect(screen.getByRole('table')).toBeInTheDocument()
      })

      // Navigate to work packages
      const wpButtons = screen.getAllByLabelText(/work.*package/i)
      fireEvent.click(wpButtons[0])

      expect(screen.getByTestId('work-packages-section')).toBeInTheDocument()

      // Click back
      fireEvent.click(screen.getByText('Back'))

      // Should return to the project list
      await waitFor(() => {
        expect(screen.getByRole('table')).toBeInTheDocument()
      })
      expect(screen.queryByTestId('work-packages-section')).not.toBeInTheDocument()
    })
  })
})
