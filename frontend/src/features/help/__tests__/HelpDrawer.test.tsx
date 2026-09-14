/**
 * Tests for the HelpDrawer component.
 *
 * Covers:
 * - Rendering the search input when opened
 * - Showing context-relevant articles based on the current route
 * - Showing "no help available" when no articles match the route
 * - Search filtering by title
 * - Search filtering by body content
 * - Clicking an article shows its content inline (no navigation)
 * - Back button returns to the article list
 * - Property (fast-check): searching with any substring of a title always returns that article
 *
 * Mocks: react-router-dom (useLocation), i18n (useTranslation)
 */

// @vitest-environment jsdom

import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import * as fc from 'fast-check'
import { MantineProvider } from '@mantine/core'
import type { ReactNode } from 'react'

// Mock window.matchMedia for Mantine components in jsdom
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

// --- Mocks ---

const mockLocation = { pathname: '/', search: '', hash: '', state: null, key: 'default' }

vi.mock('react-router-dom', () => ({
  useLocation: () => mockLocation,
  useNavigate: () => vi.fn(),
}))

vi.mock('../../../i18n', () => ({
  useTranslation: () => ({ locale: 'de', t: (key: string) => key }),
}))

// Import after mocks are set up
import { HelpDrawer } from '../HelpDrawer'
import { articles } from '../content/de'

// --- Helpers ---

function setRoute(pathname: string) {
  mockLocation.pathname = pathname
}

/** Wraps component with MantineProvider for Mantine components to work. */
function renderWithProviders(ui: ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>)
}

// --- Tests ---

describe('HelpDrawer', () => {
  beforeEach(() => {
    setRoute('/')
  })

  it('renders search input when opened', () => {
    renderWithProviders(<HelpDrawer opened={true} onClose={vi.fn()} />)

    const searchInput = screen.getByPlaceholderText('Hilfe durchsuchen…')
    expect(searchInput).toBeInTheDocument()
  })

  it('shows context-relevant articles for the /planning route', () => {
    setRoute('/planning')

    renderWithProviders(<HelpDrawer opened={true} onClose={vi.fn()} />)

    // Articles with routes including '/planning' should appear
    const planningArticles = articles.filter((a) =>
      a.routes?.some((r) => '/planning' === r || '/planning'.startsWith(r + '/')),
    )

    for (const article of planningArticles) {
      expect(screen.getByText(article.title)).toBeInTheDocument()
    }
  })

  it('shows "no help available" when no articles match the route', () => {
    setRoute('/some-unknown-route-with-no-articles')

    renderWithProviders(<HelpDrawer opened={true} onClose={vi.fn()} />)

    expect(screen.getByText('Keine Hilfe für diese Seite verfügbar.')).toBeInTheDocument()
  })

  it('search filters articles by title', () => {
    setRoute('/unknown-route')

    renderWithProviders(<HelpDrawer opened={true} onClose={vi.fn()} />)

    const searchInput = screen.getByPlaceholderText('Hilfe durchsuchen…')
    fireEvent.change(searchInput, { target: { value: 'Erste Schritte' } })

    expect(screen.getByText('Erste Schritte')).toBeInTheDocument()
  })

  it('search filters articles by body content', () => {
    setRoute('/unknown-route')

    renderWithProviders(<HelpDrawer opened={true} onClose={vi.fn()} />)

    const searchInput = screen.getByPlaceholderText('Hilfe durchsuchen…')
    // Search for a term that appears in the body of the capacity explanation article
    fireEvent.change(searchInput, { target: { value: 'Auslastung' } })

    // The capacity model article contains "Auslastung" in its body
    expect(screen.getByText('Wie funktioniert die Kapazitätsberechnung?')).toBeInTheDocument()
  })

  it('clicking an article shows its content inline (not navigating away)', () => {
    setRoute('/')

    renderWithProviders(<HelpDrawer opened={true} onClose={vi.fn()} />)

    // The "Erste Schritte" article should be visible on the "/" route
    const articleCard = screen.getByText('Erste Schritte')
    fireEvent.click(articleCard)

    // After clicking, the article body content should be rendered inline
    // The article contains "Willkommen bei Capado" in its body
    expect(screen.getByText('Erste Schritte')).toBeInTheDocument()
    // The search input should no longer be visible (we're in detail view)
    expect(screen.queryByPlaceholderText('Hilfe durchsuchen…')).not.toBeInTheDocument()
  })

  it('back button returns to article list', () => {
    setRoute('/')

    renderWithProviders(<HelpDrawer opened={true} onClose={vi.fn()} />)

    // Click an article to enter detail view
    const articleCard = screen.getByText('Erste Schritte')
    fireEvent.click(articleCard)

    // Verify we're in detail view (no search input)
    expect(screen.queryByPlaceholderText('Hilfe durchsuchen…')).not.toBeInTheDocument()

    // Click the back button
    const backButton = screen.getByTestId('help-back-button')
    fireEvent.click(backButton)

    // Should be back to list view with search input
    expect(screen.getByPlaceholderText('Hilfe durchsuchen…')).toBeInTheDocument()
  })

  describe('Property-based: substring search', () => {
    it('searching with any substring of a title always returns that article', () => {
      // Filter to articles with titles long enough to extract substrings
      const titledArticles = articles.filter((a) => a.title.length >= 3)

      fc.assert(
        fc.property(
          fc.integer({ min: 0, max: titledArticles.length - 1 }),
          fc.integer({ min: 0, max: 100 }),
          fc.integer({ min: 1, max: 100 }),
          (articleIdx, startOffset, length) => {
            const article = titledArticles[articleIdx]
            const title = article.title

            // Compute a valid substring of the title
            const start = startOffset % title.length
            const end = Math.min(start + Math.max(length % title.length, 1), title.length)
            const substring = title.slice(start, end)

            // Skip empty substrings
            fc.pre(substring.trim().length > 0)

            const { unmount } = renderWithProviders(<HelpDrawer opened={true} onClose={vi.fn()} />)

            const searchInput = screen.getByPlaceholderText('Hilfe durchsuchen…')
            fireEvent.change(searchInput, { target: { value: substring } })

            // The article with this title should appear in results
            expect(screen.getByText(article.title)).toBeInTheDocument()

            unmount()
          },
        ),
        { numRuns: 30 },
      )
    })
  })
})
