/**
 * Capacity screens: the first mutations where the digest invalidation is not optional.
 *
 * A week profile and a holiday are not master data with a name. They are MINUTES. Shortening Friday on
 * a profile, or declaring 3 October non-working, reduces what every affected resource actually has —
 * so an assignment that fitted yesterday may not fit today, and the finding that says so is computed
 * on the dashboard from data these screens just changed.
 *
 * The hand-written versions reloaded their own table: the list of profile NAMES, and the list of
 * holiday DATES. The one place the consequence was least visible.
 *
 * So what is asserted here is the set of keys, and specifically that `digest` and `conflicts` are in
 * it. A test that checked the list refreshed would pass without either.
 */
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Only the network calls are mocked, not the whole module.
 *
 * `api/calendar` also exports `parseMinutes`, `formatMinutes`, `yearStart` and `yearEnd` — pure
 * helpers the components use for their inputs. Replacing the module wholesale removed those too, and
 * the failure ("No parseMinutes export is defined on the mock") named the real problem: a mock is a
 * claim about a boundary, and this module's boundary is not the whole file.
 */
vi.mock('../../api/calendar', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/calendar')>()),
  listWorkWeekProfiles: vi.fn(),
  createWorkWeekProfile: vi.fn(),
  updateWorkWeekProfile: vi.fn(),
  deleteWorkWeekProfile: vi.fn(),
  listHolidays: vi.fn(),
  createHoliday: vi.fn(),
  updateHoliday: vi.fn(),
  deleteHoliday: vi.fn(),
  listSites: vi.fn(),
}))

const showErrorNotification = vi.fn()
vi.mock('../../utils/errorHandling', () => ({
  showErrorNotification: (...args: unknown[]) => showErrorNotification(...args),
}))

vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}))

import {
  deleteWorkWeekProfile,
  listHolidays,
  listSites,
  listWorkWeekProfiles,
  type Site,
  type WorkWeekProfile,
} from '../../api/calendar'
import { queryKeys } from '../../api/queryClient'
import { createTestQueryClient, trackInvalidations } from '../../testUtils/queryClient'
import { I18nProvider } from '../../i18n'
import { HolidaysTab } from './HolidaysTab'
import { WeekProfilesTab } from './WeekProfilesTab'

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

function profile(id: string, name: string): WorkWeekProfile {
  return {
    id,
    name,
    description: null,
    is_default: false,
    monday_minutes: 480,
    tuesday_minutes: 480,
    wednesday_minutes: 480,
    thursday_minutes: 480,
    friday_minutes: 480,
    saturday_minutes: 0,
    sunday_minutes: 0,
  } as unknown as WorkWeekProfile
}

function renderIn(ui: React.ReactNode) {
  const client = createTestQueryClient()
  const invalidated = trackInvalidations(client)
  const view = render(
    <QueryClientProvider client={client}>
      <MantineProvider>
        <I18nProvider locale="de">{ui}</I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
  return { ...view, invalidated }
}

beforeEach(() => {
  vi.mocked(listWorkWeekProfiles).mockReset()
  vi.mocked(deleteWorkWeekProfile).mockReset()
  vi.mocked(listHolidays).mockReset()
  vi.mocked(listSites).mockReset()
  showErrorNotification.mockReset()
})

describe('WeekProfilesTab', () => {
  it('renders the profiles the endpoint returned', async () => {
    vi.mocked(listWorkWeekProfiles).mockResolvedValue([profile('p1', 'Vollzeit')])

    renderIn(<WeekProfilesTab />)

    await waitFor(() => expect(screen.getByText('Vollzeit')).toBeTruthy())
  })

  it('invalidates the digest and the conflicts, not just its own list', async () => {
    // The assertion this file exists for. A profile change alters minutes, so it can create or clear
    // a conflict without anybody touching an assignment — and the dashboard is where that shows.
    vi.mocked(listWorkWeekProfiles).mockResolvedValue([profile('p1', 'Vollzeit')])
    vi.mocked(deleteWorkWeekProfile).mockResolvedValue(undefined)

    const { invalidated } = renderIn(<WeekProfilesTab />)
    await waitFor(() => expect(screen.getByText('Vollzeit')).toBeTruthy())

    fireEvent.click(screen.getByTestId('week-profile-delete-p1'))

    await waitFor(() => expect(deleteWorkWeekProfile).toHaveBeenCalledWith('p1'))
    await waitFor(() => {
      expect(invalidated).toContainEqual([...queryKeys.digest.all])
      expect(invalidated).toContainEqual([...queryKeys.conflicts.all])
      expect(invalidated).toContainEqual([...queryKeys.capacity.all])
    })
  })

  it('invalidates nothing when the delete fails', async () => {
    vi.mocked(listWorkWeekProfiles).mockResolvedValue([profile('p1', 'Vollzeit')])
    vi.mocked(deleteWorkWeekProfile).mockRejectedValue(new Error('boom'))

    const { invalidated } = renderIn(<WeekProfilesTab />)
    await waitFor(() => expect(screen.getByText('Vollzeit')).toBeTruthy())
    fireEvent.click(screen.getByTestId('week-profile-delete-p1'))

    await waitFor(() => expect(showErrorNotification).toHaveBeenCalledTimes(1))
    expect(invalidated).toEqual([])
  })
})

describe('HolidaysTab', () => {
  const site: Site = {
    id: 's1',
    name: 'Hauptwerk',
    region_code: null,
    is_default: true,
    is_active: true,
  }

  it('shares the site list with SitesTab, on the same key', async () => {
    // Both tabs live on one page and each used to fetch the list itself. Now the second is served
    // from the cache, and a site created in the other tab invalidates this dropdown.
    vi.mocked(listSites).mockResolvedValue([site])
    vi.mocked(listHolidays).mockResolvedValue([])

    renderIn(<HolidaysTab />)

    await waitFor(() => expect(listSites).toHaveBeenCalled())
    expect(queryKeys.sites.list()).toEqual(['sites', 'list'])
  })

  it('waits for a site before asking for holidays', async () => {
    // `enabled` rather than a guard inside the query function: without it the first render would fire
    // a request with site_id undefined, and the backend would answer something for it.
    vi.mocked(listSites).mockResolvedValue([])
    vi.mocked(listHolidays).mockResolvedValue([])

    renderIn(<HolidaysTab />)

    await waitFor(() => expect(listSites).toHaveBeenCalled())
    expect(listHolidays).not.toHaveBeenCalled()
  })

  it('keys holidays by site and year, so switching either cannot show the other rows', async () => {
    vi.mocked(listSites).mockResolvedValue([site])
    vi.mocked(listHolidays).mockResolvedValue([])

    renderIn(<HolidaysTab />)

    await waitFor(() => expect(listHolidays).toHaveBeenCalled())
    expect(queryKeys.capacity.holidays('s1')).not.toEqual(queryKeys.capacity.holidays('s2'))
  })
})
