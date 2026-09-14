/**
 * Tests for the digest panel.
 *
 * Two things are worth asserting here, and neither is about layout.
 *
 * The truncation notice must appear when the backend suppressed findings. That notice is the
 * panel's honesty mechanism: without it a capped list looks complete, and somebody reading it
 * would conclude there is nothing else — the opposite of what a digest is for.
 *
 * The panel must NOT re-order or re-group. The backend already ordered by urgency and the
 * nightly job will use that same order; a second opinion here would mean two sources of truth
 * about what matters.
 *
 * All fixtures are fictional.
 */

// @vitest-environment jsdom

import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'

import { createTestQueryClient } from '../../testUtils/queryClient'
import { I18nProvider } from '../../i18n'
import type { DigestResponse } from '../../api/digest'

vi.mock('../../api/digest', () => ({
  getDigest: vi.fn(),
}))

import { getDigest } from '../../api/digest'
import { DigestPanel } from './DigestPanel'

beforeAll(() => {
  // Mantine reads matchMedia during render; jsdom does not provide it.
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  })
})

function renderPanel() {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MantineProvider>
        <I18nProvider locale="en">
          <DigestPanel />
        </I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
}

const BASE: DigestResponse = {
  generated_for: '2026-08-26',
  counts: { critical: 0, warning: 0, info: 0 },
  findings: [],
  suppressed_count: 0,
}

describe('DigestPanel', () => {
  beforeEach(() => {
    vi.mocked(getDigest).mockReset()
  })

  it('reports an all-clear rather than rendering an empty box', async () => {
    vi.mocked(getDigest).mockResolvedValue(BASE)
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText(/kein handlungsbedarf|nothing needs attention/i)).toBeInTheDocument()
    })
  })

  it('renders findings in the order the backend returned them', async () => {
    vi.mocked(getDigest).mockResolvedValue({
      ...BASE,
      counts: { critical: 1, warning: 1, info: 0 },
      findings: [
        {
          kind: 'qualification_expired',
          severity: 'critical',
          params: {
            skill: 'Kranschein',
            person: 'B. Beispiel',
            days: '5',
            date: '2026-08-21',
          },
          due: '2026-08-21',
          resource_id: null,
          work_package_id: null,
          project_id: null,
        },
        {
          kind: 'dependency_violated',
          severity: 'warning',
          params: { successor: 'WP-B', predecessor: 'WP-A', days: '4' },
          due: '2026-09-20',
          resource_id: null,
          work_package_id: null,
          project_id: null,
        },
      ],
    })
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText(/Kranschein/)).toBeInTheDocument()
    })
    const titles = screen.getAllByText(/Kranschein|WP-B/)
    expect(titles[0].textContent).toMatch(/Kranschein/)
  })

  it('marks an already-due finding as overdue rather than as a negative countdown', async () => {
    vi.mocked(getDigest).mockResolvedValue({
      ...BASE,
      counts: { critical: 1, warning: 0, info: 0 },
      findings: [
        {
          kind: 'qualification_expired',
          severity: 'critical',
          params: {
            skill: 'Schweißzeugnis',
            person: 'A. Beispiel',
            days: '10',
            date: '2026-08-16',
          },
          due: '2026-08-16',
          resource_id: null,
          work_package_id: null,
          project_id: null,
        },
      ],
    })
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText(/überfällig|overdue/i)).toBeInTheDocument()
    })
  })

  it('says the list is truncated when the backend suppressed findings', async () => {
    vi.mocked(getDigest).mockResolvedValue({
      ...BASE,
      counts: { critical: 1, warning: 0, info: 0 },
      findings: [
        {
          kind: 'requirement_uncovered',
          severity: 'critical',
          params: { skill: 'Drehen', work_package: 'WP-9', needed_by: '2026-08-30' },
          due: '2026-08-30',
          resource_id: null,
          work_package_id: null,
          project_id: null,
        },
      ],
      suppressed_count: 42,
    })
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText(/42/)).toBeInTheDocument()
    })
  })

  it('does not claim all-clear while still loading', async () => {
    vi.mocked(getDigest).mockReturnValue(new Promise(() => {}))
    renderPanel()
    expect(screen.queryByText(/kein handlungsbedarf|nothing needs attention/i)).toBeNull()
  })
})

/**
 * Dates inside a finding's sentence follow the locale.
 *
 * This panel was the one screen rendering a raw `2026-09-01` while every other screen showed
 * `01.09.2026` — the backend used to interpolate the date itself, so there was nothing here
 * to format. Now that it sends the value, the date is formatted like the rest of the app.
 */
describe('DigestPanel dates', () => {
  function renderIn(locale: 'de' | 'en') {
    return render(
      <MantineProvider>
        <QueryClientProvider client={createTestQueryClient()}>
          <I18nProvider locale={locale}>
            <DigestPanel />
          </I18nProvider>
        </QueryClientProvider>
      </MantineProvider>,
    )
  }

  const UNCOVERED: DigestResponse = {
    ...BASE,
    counts: { critical: 1, warning: 0, info: 0 },
    findings: [
      {
        kind: 'requirement_uncovered',
        severity: 'critical',
        params: { skill: 'Drehen', work_package: 'WP-9', needed_by: '2026-09-01' },
        due: '2026-09-01',
        resource_id: null,
        work_package_id: null,
        project_id: null,
      },
    ],
  }

  beforeEach(() => {
    vi.mocked(getDigest).mockReset()
  })

  it('renders a German date as DD.MM.YYYY inside the sentence', async () => {
    vi.mocked(getDigest).mockResolvedValue(UNCOVERED)
    renderIn('de')
    await waitFor(() => {
      expect(screen.getByText(/01\.09\.2026/)).toBeInTheDocument()
    })
    expect(screen.queryByText(/2026-09-01/)).toBeNull()
  })

  it('renders an English date as ISO inside the sentence', async () => {
    vi.mocked(getDigest).mockResolvedValue(UNCOVERED)
    renderIn('en')
    await waitFor(() => {
      expect(screen.getByText(/2026-09-01/)).toBeInTheDocument()
    })
  })

  it('leaves a non-date parameter alone', async () => {
    // Dates are picked by the VALUE's shape, so the rule has to be narrow enough not to
    // touch anything else. A day COUNT is the case that would break first: "5" must stay "5".
    vi.mocked(getDigest).mockResolvedValue({
      ...BASE,
      counts: { critical: 1, warning: 0, info: 0 },
      findings: [
        {
          kind: 'qualification_expired',
          severity: 'critical',
          params: {
            skill: 'Kranschein',
            person: 'B. Beispiel',
            days: '5',
            date: '2026-08-21',
          },
          due: '2026-08-21',
          resource_id: null,
          work_package_id: null,
          project_id: null,
        },
      ],
    })
    renderIn('de')
    await waitFor(() => {
      expect(screen.getByText(/Kranschein/)).toBeInTheDocument()
    })
    // "seit 5 Tagen (21.08.2026)" — the count untouched, the date formatted.
    expect(screen.getByText(/seit 5 Tagen \(21\.08\.2026\)/)).toBeInTheDocument()
  })
})
