/**
 * Integration tests for the DataTable shared layout component.
 *
 * Verifies:
 * - Loading state renders a loader, not the table
 * - Empty state renders the empty message, not the table
 * - Normal state renders a table with proper semantics (thead, tbody)
 * - Custom testId is applied
 */

// @vitest-environment jsdom

import { describe, it, expect, vi, beforeAll } from 'vitest'
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import { MantineProvider, Table } from '@mantine/core'
import { DataTable } from './DataTable'

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

function renderWithMantine(ui: React.ReactElement) {
  return render(<MantineProvider>{ui}</MantineProvider>)
}

describe('DataTable', () => {
  const head = (
    <Table.Tr>
      <Table.Th>Name</Table.Th>
      <Table.Th>Value</Table.Th>
    </Table.Tr>
  )

  const rows = (
    <>
      <Table.Tr>
        <Table.Td>Item 1</Table.Td>
        <Table.Td>100</Table.Td>
      </Table.Tr>
      <Table.Tr>
        <Table.Td>Item 2</Table.Td>
        <Table.Td>200</Table.Td>
      </Table.Tr>
    </>
  )

  it('renders a loader when loading is true', () => {
    renderWithMantine(
      <DataTable loading head={head}>
        {rows}
      </DataTable>,
    )

    expect(document.querySelector('.mantine-Loader-root')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('renders empty message when empty is true', () => {
    renderWithMantine(
      <DataTable empty emptyMessage="No records found." head={head}>
        {rows}
      </DataTable>,
    )

    expect(screen.getByText('No records found.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('renders default empty message when no emptyMessage provided', () => {
    renderWithMantine(
      <DataTable empty head={head}>
        {rows}
      </DataTable>,
    )

    expect(screen.getByText('No data available.')).toBeInTheDocument()
  })

  it('renders a table with proper semantics when data is present', () => {
    renderWithMantine(<DataTable head={head}>{rows}</DataTable>)

    const table = screen.getByRole('table')
    expect(table).toBeInTheDocument()

    // Verify thead and tbody exist
    const thead = table.querySelector('thead')
    const tbody = table.querySelector('tbody')
    expect(thead).toBeInTheDocument()
    expect(tbody).toBeInTheDocument()

    // Verify header content
    expect(screen.getByText('Name')).toBeInTheDocument()
    expect(screen.getByText('Value')).toBeInTheDocument()

    // Verify body content
    expect(screen.getByText('Item 1')).toBeInTheDocument()
    expect(screen.getByText('Item 2')).toBeInTheDocument()
  })

  it('applies data-testid when testId prop is provided', () => {
    renderWithMantine(
      <DataTable head={head} testId="my-table">
        {rows}
      </DataTable>,
    )

    expect(screen.getByTestId('my-table')).toBeInTheDocument()
  })
})
