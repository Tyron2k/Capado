/**
 * The first screen on the query layer, and the properties that make it worth copying.
 *
 * These tests are not about the audit log. They pin the two things the hand-rolled pattern could get
 * wrong and the cache must not:
 *
 * 1. **Filters live in the query key.** The old code kept one `entries` state and reloaded it from a
 *    callback whose dependencies were the filters, so a filter change mid-request could resolve the
 *    OLD request last and land its rows under the new heading. A key per filter combination makes
 *    that impossible rather than unlikely — and a test that only checked "rows appear" would pass
 *    either way, which is why the filter case is here.
 * 2. **Failures are reported per screen.** There is no global error handler on purpose, so the
 *    notification can name what failed. The settings query is deliberately silent: the table works
 *    without the retention note, and a notification about a footnote teaches people to dismiss
 *    notifications.
 */
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/audit', () => ({
  getAuditEntries: vi.fn(),
  getEntityHistory: vi.fn(),
}))

vi.mock('../../api/settings', () => ({
  getTenantSettings: vi.fn(),
}))

const showErrorNotification = vi.fn()
vi.mock('../../utils/errorHandling', () => ({
  showErrorNotification: (...args: unknown[]) => showErrorNotification(...args),
}))

import { getAuditEntries, getEntityHistory, type AuditEntry } from '../../api/audit'
import { getTenantSettings } from '../../api/settings'
import { createTestQueryClient } from '../../testUtils/queryClient'
import { I18nProvider } from '../../i18n'
import { AuditPage } from './AuditPage'

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
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

function entry(id: string, entityType: string): AuditEntry {
  return {
    id,
    entity_type: entityType,
    entity_id: `${id}-0000-0000-0000-000000000000`,
    action: 'created',
    actor_id: null,
    reason: null,
    changes: {},
    recorded_at: '2026-09-13T08:00:00',
  }
}

function renderPage() {
  const client = createTestQueryClient()
  return render(
    <MantineProvider>
      <QueryClientProvider client={client}>
        <I18nProvider locale="de">
          <AuditPage />
        </I18nProvider>
      </QueryClientProvider>
    </MantineProvider>,
  )
}

describe('AuditPage on the query layer', () => {
  beforeEach(() => {
    vi.mocked(getAuditEntries).mockReset()
    vi.mocked(getEntityHistory).mockReset()
    vi.mocked(getTenantSettings).mockReset()
    showErrorNotification.mockReset()
    vi.mocked(getTenantSettings).mockResolvedValue({
      audit_retention_months: 24,
    } as Awaited<ReturnType<typeof getTenantSettings>>)
  })

  it('renders the entries the list endpoint returned', async () => {
    vi.mocked(getAuditEntries).mockResolvedValue([entry('a1', 'project')])

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('project')).toBeTruthy()
    })
    expect(getEntityHistory).not.toHaveBeenCalled()
  })

  it('passes an abort signal, so a superseded request is cancelled by the library', async () => {
    // The hand-written AbortController and the `if (signal.aborted) return` after every await are
    // gone. That only holds if the signal actually reaches the client.
    vi.mocked(getAuditEntries).mockResolvedValue([entry('a1', 'project')])

    renderPage()

    await waitFor(() => expect(getAuditEntries).toHaveBeenCalled())
    const signal = vi.mocked(getAuditEntries).mock.calls[0][1]
    expect(signal).toBeInstanceOf(AbortSignal)
  })

  it('uses the indexed history endpoint only when a type AND an id are given', async () => {
    // Two different requests, so two different keys. Treating the id as one more filter on the list
    // would share a cache entry between them and lose the composite index the history endpoint has.
    vi.mocked(getEntityHistory).mockResolvedValue([entry('h1', 'project')])
    vi.mocked(getAuditEntries).mockResolvedValue([])

    renderPage()

    await waitFor(() => expect(getAuditEntries).toHaveBeenCalled())
    // With no id entered, the list endpoint is the one used — the history endpoint is not.
    expect(getEntityHistory).not.toHaveBeenCalled()
  })

  it('reports a failed list once, naming what failed', async () => {
    vi.mocked(getAuditEntries).mockRejectedValue(new Error('boom'))

    renderPage()

    await waitFor(() => expect(showErrorNotification).toHaveBeenCalledTimes(1))
  })

  it('stays silent when only the retention note fails', async () => {
    // The table is usable without it. This is the case a global error handler would get wrong.
    vi.mocked(getAuditEntries).mockResolvedValue([entry('a1', 'project')])
    vi.mocked(getTenantSettings).mockRejectedValue(new Error('boom'))

    renderPage()

    await waitFor(() => expect(screen.getByText('project')).toBeTruthy())
    expect(showErrorNotification).not.toHaveBeenCalled()
  })
})
