/**
 * Integration tests for the PageTabs shared layout component.
 *
 * Verifies:
 * - Title is rendered as an h2 heading
 * - All tabs are rendered with correct labels
 * - First tab is active by default
 * - Custom defaultTab selects the correct tab
 * - Tab content is rendered for the active tab
 */

// @vitest-environment jsdom

import { describe, it, expect, vi, beforeAll } from 'vitest'
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { render, screen } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { IconUsers, IconSettings } from '@tabler/icons-react'
import { PageTabs, type TabDefinition } from './PageTabs'

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

const testTabs: TabDefinition[] = [
  { value: 'people', label: 'People', icon: IconUsers, content: <p>People content</p> },
  { value: 'settings', label: 'Settings', icon: IconSettings, content: <p>Settings content</p> },
]

describe('PageTabs', () => {
  it('renders the title as an h2 heading', () => {
    renderWithMantine(<PageTabs title="Resources" tabs={testTabs} />)

    const heading = screen.getByRole('heading', { level: 2 })
    expect(heading).toHaveTextContent('Resources')
  })

  it('renders all tab labels', () => {
    renderWithMantine(<PageTabs title="Resources" tabs={testTabs} />)

    expect(screen.getByRole('tab', { name: /People/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Settings/i })).toBeInTheDocument()
  })

  it('first tab is active by default', () => {
    renderWithMantine(<PageTabs title="Resources" tabs={testTabs} />)

    const peopleTab = screen.getByRole('tab', { name: /People/i })
    expect(peopleTab).toHaveAttribute('aria-selected', 'true')
  })

  it('renders content for the active tab', () => {
    renderWithMantine(<PageTabs title="Resources" tabs={testTabs} />)

    expect(screen.getByText('People content')).toBeInTheDocument()
  })

  it('respects custom defaultTab', () => {
    renderWithMantine(<PageTabs title="Resources" tabs={testTabs} defaultTab="settings" />)

    const settingsTab = screen.getByRole('tab', { name: /Settings/i })
    expect(settingsTab).toHaveAttribute('aria-selected', 'true')
  })
})
