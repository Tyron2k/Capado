/**
 * Unit tests for the PlanningPage thin wrapper component.
 *
 * Verifies:
 * - Renders a single PageTabs with correct title and 3 tabs
 * - Overview tab is shown by default
 * - PlanningOverviewPanel, AssignmentsPanel and PlanningAdminPanel are referenced in tabs
 */

import { describe, it, expect, vi, beforeAll } from 'vitest'
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { MemoryRouter } from 'react-router-dom'
import { PlanningPage } from './PlanningPage'

// Mock i18n to return keys as-is
vi.mock('../../i18n', () => ({
  useTranslation: () => ({ locale: 'en', t: (key: string) => key }),
}))

// Mock panel components to avoid their full dependency trees
vi.mock('./AssignmentsPanel', () => ({
  AssignmentsPanel: () => <div data-testid="assignments-panel">AssignmentsPanel</div>,
}))

vi.mock('./PlanningOverviewPanel', () => ({
  PlanningOverviewPanel: () => <div data-testid="overview-panel">PlanningOverviewPanel</div>,
}))

vi.mock('./PlanningAdminPanel', () => ({
  PlanningAdminPanel: () => <div data-testid="planning-admin-panel">PlanningAdminPanel</div>,
}))

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

function renderWithProviders(ui: React.ReactElement, initialEntries: string[] = ['/planning']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <MantineProvider>{ui}</MantineProvider>
    </MemoryRouter>,
  )
}

describe('PlanningPage', () => {
  it('renders a page title', () => {
    renderWithProviders(<PlanningPage />)

    const heading = screen.getByRole('heading', { level: 2 })
    expect(heading).toHaveTextContent('planning.title')
  })

  it('renders exactly 3 tabs', () => {
    renderWithProviders(<PlanningPage />)

    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(3)
  })

  it('renders Overview, Assignments and Admin tab labels', () => {
    renderWithProviders(<PlanningPage />)

    expect(screen.getByRole('tab', { name: /planning\.tabOverview/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /planning\.tabAssignments/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /admin\.title/i })).toBeInTheDocument()
  })

  it('defaults to Overview tab', () => {
    renderWithProviders(<PlanningPage />, ['/planning'])

    const overviewTab = screen.getByRole('tab', { name: /planning\.tabOverview/i })
    expect(overviewTab).toHaveAttribute('aria-selected', 'true')
  })

  it('renders PlanningOverviewPanel in the overview tab', () => {
    renderWithProviders(<PlanningPage />, ['/planning'])

    expect(screen.getByTestId('overview-panel')).toBeInTheDocument()
  })
})
