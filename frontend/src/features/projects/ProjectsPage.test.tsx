/**
 * Unit tests for the ProjectsPage wrapper component.
 *
 * Verifies:
 * - Renders PageTabs with correct title and 2 tabs (Projects + Admin)
 * - ProjectsPanel and ProjectAdminPanel are referenced in tabs
 */

// @vitest-environment jsdom

import { describe, it, expect, vi, beforeAll } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'

import { createTestQueryClient } from '../../testUtils/queryClient'
import type { ReactNode } from 'react'

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

vi.mock('../../i18n', () => ({
  useTranslation: () => ({ locale: 'en', t: (key: string) => key }),
}))

vi.mock('./ProjectsPanel', () => ({
  ProjectsPanel: () => <div data-testid="projects-panel">ProjectsPanel</div>,
}))

vi.mock('./ProjectAdminPanel', () => ({
  ProjectAdminPanel: () => <div data-testid="project-admin-panel">ProjectAdminPanel</div>,
}))

import { ProjectsPage } from './ProjectsPage'

function renderWithProviders(ui: ReactNode) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MantineProvider>{ui}</MantineProvider>
    </QueryClientProvider>,
  )
}

describe('ProjectsPage', () => {
  it('renders a page title', () => {
    renderWithProviders(<ProjectsPage />)
    const heading = screen.getByRole('heading', { level: 2 })
    expect(heading).toHaveTextContent('projects.title')
  })

  it('renders exactly 3 tabs', () => {
    renderWithProviders(<ProjectsPage />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(3)
  })

  it('renders the Customers tab', () => {
    renderWithProviders(<ProjectsPage />)
    expect(screen.getByRole('tab', { name: /customers\.title/i })).toBeInTheDocument()
  })

  it('renders Projects tab with correct label', () => {
    renderWithProviders(<ProjectsPage />)
    expect(screen.getByRole('tab', { name: /projects\.tabProjects/i })).toBeInTheDocument()
  })

  it('renders Admin tab with correct label', () => {
    renderWithProviders(<ProjectsPage />)
    expect(screen.getByRole('tab', { name: /admin\.title/i })).toBeInTheDocument()
  })

  it('renders ProjectsPanel in the first tab', () => {
    renderWithProviders(<ProjectsPage />)
    expect(screen.getByTestId('projects-panel')).toBeInTheDocument()
  })

  it('renders ProjectAdminPanel in the second tab', () => {
    renderWithProviders(<ProjectsPage />)
    expect(screen.getByTestId('project-admin-panel')).toBeInTheDocument()
  })
})
