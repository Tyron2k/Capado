/**
 * Unit tests for PlanningAdminPanel.
 *
 * Verifies:
 * - The Import/Export section header renders.
 * - An ImportExportBar is wired to the assignments endpoints
 *   (/api/assignments/export and /api/assignments/import) — this is the
 *   gap the feature closes, so the exact paths are asserted.
 * - The CSV hint text is rendered.
 */

// @vitest-environment jsdom

import { describe, it, expect, vi, beforeAll } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
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

// Render the ImportExportBar as a stub that exposes its wiring via data attrs
// so the test can assert the assignment endpoints are correctly connected.
vi.mock('../resources/ImportExportBar', () => ({
  ImportExportBar: ({
    exportPath,
    importPath,
    filenameBase,
  }: {
    exportPath: string
    importPath: string
    filenameBase: string
  }) => (
    <div
      data-testid="import-export-bar"
      data-export-path={exportPath}
      data-import-path={importPath}
      data-filename-base={filenameBase}
    />
  ),
}))

import { PlanningAdminPanel } from './PlanningAdminPanel'

function renderWithProviders(ui: ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>)
}

describe('PlanningAdminPanel', () => {
  it('renders the Import/Export section header', () => {
    renderWithProviders(<PlanningAdminPanel />)
    expect(screen.getByText('admin.importExport')).toBeInTheDocument()
  })

  it('wires the ImportExportBar to the assignments endpoints', () => {
    renderWithProviders(<PlanningAdminPanel />)
    const bar = screen.getByTestId('import-export-bar')
    expect(bar).toHaveAttribute('data-export-path', '/api/assignments/export')
    expect(bar).toHaveAttribute('data-import-path', '/api/assignments/import')
    expect(bar).toHaveAttribute('data-filename-base', 'assignments')
  })

  it('renders the assignments CSV hint', () => {
    renderWithProviders(<PlanningAdminPanel />)
    expect(screen.getByText('admin.assignmentsCsvHint')).toBeInTheDocument()
  })
})
