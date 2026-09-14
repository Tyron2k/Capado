/**
 * THE CALENDAR API SURFACE: the four things that define working time, plus the helpers that read it.
 *
 * Sites, holidays, week profiles and profile bindings are what the capacity layer is computed FROM, so a
 * wrong path here does not produce a visible error — it produces a plan built on the wrong calendar.
 * TypeScript cannot help: every URL is a string and every wrapper returns its own type regardless of
 * which endpoint answered.
 *
 * Three details are pinned because they are decisions rather than plumbing:
 *
 *   `listSites` sends `include_inactive` ALWAYS, including as `false`. The query layer keys the site list
 *   without that flag today, and this test is what would catch it becoming a second, silently-shared
 *   variant (the same mistake `customers.list(includeInactive)` was written to avoid).
 *
 *   A binding is deleted by ITS OWN id, not by the resource it binds. The nested create route and the
 *   flat delete route look inconsistent and are not: an assignment of a profile is a thing with an
 *   identity.
 *
 *   `wrapsPastMidnight` is the one piece of real logic in this module, and it is what makes a night shift
 *   expressible: an end time that is not AFTER the start is not invalid input, it is the next morning —
 *   equal times included, which is a full day rather than nothing.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

import apiClient from '../client'
import {
  createBinding,
  createHoliday,
  createSite,
  createWorkWeekProfile,
  deactivateSite,
  deleteBinding,
  deleteHoliday,
  deleteWorkWeekProfile,
  formatMinutes,
  listBindings,
  listHolidays,
  listSites,
  listWorkWeekProfiles,
  parseMinutes,
  updateHoliday,
  updateSite,
  updateWorkWeekProfile,
  wrapsPastMidnight,
} from '../calendar'

const mocked = vi.mocked(apiClient)

beforeEach(() => {
  vi.clearAllMocks()
  mocked.get.mockResolvedValue({ data: [] } as never)
  mocked.post.mockResolvedValue({ data: {} } as never)
  mocked.put.mockResolvedValue({ data: {} } as never)
  mocked.delete.mockResolvedValue({ data: undefined } as never)
})

describe('sites', () => {
  it('always states whether inactive sites are wanted, including when they are not', async () => {
    await listSites()
    expect(mocked.get).toHaveBeenCalledWith('/api/sites', {
      params: { include_inactive: false },
    })

    await listSites(true)
    expect(mocked.get).toHaveBeenLastCalledWith('/api/sites', {
      params: { include_inactive: true },
    })
  })

  it('creates, renames and DEACTIVATES rather than deleting', async () => {
    await createSite({ name: 'Werk Süd' } as never)
    expect(mocked.post).toHaveBeenCalledWith('/api/sites', { name: 'Werk Süd' })

    await updateSite('s1', { name: 'Werk Nord' } as never)
    expect(mocked.put).toHaveBeenCalledWith('/api/sites/s1', { name: 'Werk Nord' })

    // A site that resources were filed at cannot simply vanish — the DELETE verb deactivates.
    await deactivateSite('s1')
    expect(mocked.delete).toHaveBeenCalledWith('/api/sites/s1')
  })
})

describe('holidays', () => {
  it('passes the site and the window through as query parameters', async () => {
    await listHolidays({ site_id: 's1', from: '2026-01-01', to: '2026-12-31' })
    expect(mocked.get).toHaveBeenCalledWith('/api/holidays', {
      params: { site_id: 's1', from: '2026-01-01', to: '2026-12-31' },
    })
  })

  it('accepts an empty filter, which asks for all of them', async () => {
    await listHolidays({})
    expect(mocked.get).toHaveBeenCalledWith('/api/holidays', { params: {} })
  })

  it('creates, updates and deletes', async () => {
    await createHoliday({ name: 'Tag der Arbeit', date: '2026-05-01' } as never)
    expect(mocked.post).toHaveBeenCalledWith('/api/holidays', {
      name: 'Tag der Arbeit',
      date: '2026-05-01',
    })

    await updateHoliday('h1', { name: 'Maifeiertag' } as never)
    expect(mocked.put).toHaveBeenCalledWith('/api/holidays/h1', { name: 'Maifeiertag' })

    await deleteHoliday('h1')
    expect(mocked.delete).toHaveBeenCalledWith('/api/holidays/h1')
  })
})

describe('week profiles', () => {
  it('lists, creates, updates and deletes', async () => {
    await listWorkWeekProfiles()
    expect(mocked.get).toHaveBeenCalledWith('/api/work-week-profiles')

    await createWorkWeekProfile({ name: 'Frühschicht' } as never)
    expect(mocked.post).toHaveBeenCalledWith('/api/work-week-profiles', { name: 'Frühschicht' })

    await updateWorkWeekProfile('w1', { name: 'Spätschicht' } as never)
    expect(mocked.put).toHaveBeenCalledWith('/api/work-week-profiles/w1', { name: 'Spätschicht' })

    await deleteWorkWeekProfile('w1')
    expect(mocked.delete).toHaveBeenCalledWith('/api/work-week-profiles/w1')
  })
})

describe('profile bindings', () => {
  it('can be listed per resource or per group', async () => {
    await listBindings({ resource_id: 'r1' })
    expect(mocked.get).toHaveBeenCalledWith('/api/resource-work-profiles', {
      params: { resource_id: 'r1' },
    })

    await listBindings({ group_id: 'g1' })
    expect(mocked.get).toHaveBeenLastCalledWith('/api/resource-work-profiles', {
      params: { group_id: 'g1' },
    })
  })

  it('is deleted by its own id, not by the resource it binds', async () => {
    await createBinding({ resource_id: 'r1', profile_id: 'w1' } as never)
    expect(mocked.post).toHaveBeenCalledWith('/api/resource-work-profiles', {
      resource_id: 'r1',
      profile_id: 'w1',
    })

    // A binding is a thing with an identity, which is why this route is flat where the create is not.
    await deleteBinding('b1')
    expect(mocked.delete).toHaveBeenCalledWith('/api/resource-work-profiles/b1')
  })
})

describe('reading and writing a duration', () => {
  /**
   * These are DURATIONS, not clock times, and the formatting reflects that: hours are not zero-padded,
   * because "7:30" is how long a day is and "07:30" is when a shift starts. Half hours are preserved
   * deliberately — rounding to whole hours would misreport a 7.5-hour day as 8.
   */
  it('formats hours unpadded and minutes padded', () => {
    expect(formatMinutes(0)).toBe('0:00')
    expect(formatMinutes(8 * 60)).toBe('8:00')
    expect(formatMinutes(7 * 60 + 30)).toBe('7:30')
    expect(formatMinutes(40 * 60)).toBe('40:00')
  })

  it('round-trips through its own format', () => {
    for (const minutes of [0, 30, 437, 480, 1440]) {
      expect(parseMinutes(formatMinutes(minutes))).toBe(minutes)
    }
  })

  it('accepts a bare hour, because that is how somebody types "8 hours"', () => {
    expect(parseMinutes('8')).toBe(480)
    expect(parseMinutes('8:00')).toBe(480)
    expect(parseMinutes(' 8:30 ')).toBe(510)
  })

  it('rejects what is not a duration rather than guessing', () => {
    expect(parseMinutes('')).toBeNull()
    expect(parseMinutes('abc')).toBeNull()
    // Minutes above 59 are not a duration overflow, they are a typo.
    expect(parseMinutes('8:61')).toBeNull()
    // A week has 168 hours, but a DAY cannot exceed 24 — the cap is what stops a slipped keystroke
    // becoming a fortnight.
    expect(parseMinutes('24:00')).toBe(1440)
    expect(parseMinutes('24:01')).toBeNull()
    expect(parseMinutes('99:00')).toBeNull()
  })
})

describe('a window that runs past midnight', () => {
  /**
   * `endTime <= startTime` — an end that is not AFTER the start wraps into the next day. Equal times
   * therefore wrap too, which is the deliberate reading: 06:00–06:00 is a full twenty-four hours, not a
   * zero-length shift. Callers use this to label such a row rather than drawing an interval that reads
   * backwards.
   */
  it('reads an end before the start as the next morning, which is what a night shift is', () => {
    expect(wrapsPastMidnight('22:00', '06:00')).toBe(true)
    expect(wrapsPastMidnight('06:00', '14:00')).toBe(false)
  })

  it('treats equal times as a full day rather than as nothing', () => {
    expect(wrapsPastMidnight('06:00', '06:00')).toBe(true)
  })
})
