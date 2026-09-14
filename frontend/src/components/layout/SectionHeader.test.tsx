/**
 * Integration tests for the SectionHeader shared layout component.
 *
 * Verifies:
 * - Title is rendered as an h4 heading
 * - Actions are rendered when provided
 * - No actions section when not provided
 */

// @vitest-environment jsdom

import { describe, it, expect, vi, beforeAll } from 'vitest'
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import { MantineProvider, Button } from '@mantine/core'
import { SectionHeader } from './SectionHeader'

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

describe('SectionHeader', () => {
  it('renders the title as an h4 heading', () => {
    renderWithMantine(<SectionHeader title="Active Projects" />)

    const heading = screen.getByRole('heading', { level: 4 })
    expect(heading).toHaveTextContent('Active Projects')
  })

  it('renders actions when provided', () => {
    renderWithMantine(<SectionHeader title="Skills" actions={<Button>Add Skill</Button>} />)

    expect(screen.getByRole('button', { name: 'Add Skill' })).toBeInTheDocument()
  })

  it('does not render action buttons when actions prop is omitted', () => {
    const { container } = renderWithMantine(<SectionHeader title="Skills" />)

    const buttons = container.querySelectorAll('button')
    expect(buttons.length).toBe(0)
  })
})
