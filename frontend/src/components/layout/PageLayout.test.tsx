/**
 * Integration tests for the PageLayout shared layout component.
 *
 * Verifies:
 * - Title is rendered as an h2 heading
 * - Children are rendered
 * - Header actions are rendered when provided
 * - No header actions section when not provided
 */

// @vitest-environment jsdom

import { describe, it, expect, vi, beforeAll } from 'vitest'
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import { MantineProvider, Button } from '@mantine/core'
import { PageLayout } from './PageLayout'

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

describe('PageLayout', () => {
  it('renders the title as an h2 heading', () => {
    renderWithMantine(
      <PageLayout title="Dashboard">
        <p>Content</p>
      </PageLayout>,
    )

    const heading = screen.getByRole('heading', { level: 2 })
    expect(heading).toHaveTextContent('Dashboard')
  })

  it('renders children content', () => {
    renderWithMantine(
      <PageLayout title="Test Page">
        <p>Page content here</p>
      </PageLayout>,
    )

    expect(screen.getByText('Page content here')).toBeInTheDocument()
  })

  it('renders header actions when provided', () => {
    renderWithMantine(
      <PageLayout title="Test" headerActions={<Button>Add Item</Button>}>
        <p>Content</p>
      </PageLayout>,
    )

    expect(screen.getByRole('button', { name: 'Add Item' })).toBeInTheDocument()
  })

  it('does not render header actions section when not provided', () => {
    const { container } = renderWithMantine(
      <PageLayout title="Test">
        <p>Content</p>
      </PageLayout>,
    )

    // Only one group (the title group), no extra action group
    const buttons = container.querySelectorAll('button')
    expect(buttons.length).toBe(0)
  })
})
