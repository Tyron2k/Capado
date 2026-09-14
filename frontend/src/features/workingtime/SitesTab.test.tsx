/**
 * The second screen on the query layer, and the first with a MUTATION.
 *
 * The reads were the easy half. What a mutation has to get right is saying what it made untrue — and
 * that is not always its own list. Renaming a site changes what every RESOURCE list displays, because
 * `site_name` is denormalised onto those responses. The hand-written version called `await load()`
 * and refreshed this table only, so a rename left the people and infrastructure tables showing the
 * previous name until something else happened to refetch. Nobody would have filed that as a bug;
 * they would have called the application unreliable.
 *
 * So the assertion worth making is not "the list refreshed". It is "the right set of keys was
 * invalidated", including the one belonging to a feature this file does not import.
 */
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/calendar', () => ({
  listSites: vi.fn(),
  createSite: vi.fn(),
  updateSite: vi.fn(),
  deactivateSite: vi.fn(),
}))

const showErrorNotification = vi.fn()
vi.mock('../../utils/errorHandling', () => ({
  showErrorNotification: (...args: unknown[]) => showErrorNotification(...args),
}))

vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}))

import { createSite, deactivateSite, listSites, updateSite, type Site } from '../../api/calendar'
import { queryKeys } from '../../api/queryClient'
import { createTestQueryClient, trackInvalidations } from '../../testUtils/queryClient'
import { I18nProvider } from '../../i18n'
import { SitesTab } from './SitesTab'

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

function site(id: string, name: string): Site {
  return { id, name, region_code: null, is_default: false, is_active: true }
}

function renderTab() {
  const client = createTestQueryClient()
  const invalidated = trackInvalidations(client)

  const view = render(
    <MantineProvider>
      <QueryClientProvider client={client}>
        <I18nProvider locale="de">
          <SitesTab />
        </I18nProvider>
      </QueryClientProvider>
    </MantineProvider>,
  )
  return { ...view, invalidated }
}

describe('SitesTab mutations', () => {
  beforeEach(() => {
    vi.mocked(listSites).mockReset()
    vi.mocked(createSite).mockReset()
    vi.mocked(updateSite).mockReset()
    vi.mocked(deactivateSite).mockReset()
    showErrorNotification.mockReset()
  })

  it('renders the sites the list endpoint returned', async () => {
    vi.mocked(listSites).mockResolvedValue([site('s1', 'Hauptwerk')])

    renderTab()

    await waitFor(() => expect(screen.getByText('Hauptwerk')).toBeTruthy())
  })

  it('invalidates the resource lists too when a site is deactivated', async () => {
    // THE POINT OF THIS FILE. The resources key belongs to a feature this file does not import, and
    // invalidating it is currently a no-op because those screens are not on the query layer yet.
    // Asserting it now is what stops it being forgotten when they are — which is the exact class of
    // forgetting the layer exists to remove.
    vi.mocked(listSites).mockResolvedValue([site('s1', 'Hauptwerk')])
    vi.mocked(deactivateSite).mockResolvedValue(undefined)

    const { invalidated } = renderTab()
    await waitFor(() => expect(screen.getByText('Hauptwerk')).toBeTruthy())

    fireEvent.click(screen.getByTestId('site-deactivate-s1'))

    await waitFor(() => expect(deactivateSite).toHaveBeenCalledWith('s1'))
    await waitFor(() => {
      expect(invalidated).toEqual(
        expect.arrayContaining([[...queryKeys.sites.all], [...queryKeys.resources.all]]),
      )
    })
  })

  it('invalidates by the coarse prefix, not by the exact list key', async () => {
    // ['sites'] rather than ['sites','list']: over-invalidating costs a request, while
    // under-invalidating shows a value that is no longer true. The prefix is the correct default.
    vi.mocked(listSites).mockResolvedValue([site('s1', 'Hauptwerk')])
    vi.mocked(deactivateSite).mockResolvedValue(undefined)

    const { invalidated } = renderTab()
    await waitFor(() => expect(screen.getByText('Hauptwerk')).toBeTruthy())
    fireEvent.click(screen.getByTestId('site-deactivate-s1'))

    await waitFor(() => expect(deactivateSite).toHaveBeenCalled())
    expect(invalidated).not.toContainEqual([...queryKeys.sites.list()])
  })

  it('reports a failed mutation and invalidates nothing', async () => {
    // An invalidation after a failed write would refetch data that did not change, and the refetch
    // succeeding can read as if the write had.
    vi.mocked(listSites).mockResolvedValue([site('s1', 'Hauptwerk')])
    vi.mocked(deactivateSite).mockRejectedValue(new Error('boom'))

    const { invalidated } = renderTab()
    await waitFor(() => expect(screen.getByText('Hauptwerk')).toBeTruthy())
    fireEvent.click(screen.getByTestId('site-deactivate-s1'))

    await waitFor(() => expect(showErrorNotification).toHaveBeenCalledTimes(1))
    expect(invalidated).toEqual([])
  })

  it('reports a failed list', async () => {
    vi.mocked(listSites).mockRejectedValue(new Error('boom'))

    renderTab()

    await waitFor(() => expect(showErrorNotification).toHaveBeenCalledTimes(1))
  })
})
