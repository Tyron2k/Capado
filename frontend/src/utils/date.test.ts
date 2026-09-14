/**
 * Tests for `utils/date`, organised like the module itself.
 *
 * 1. Display formatting — ISO string in, German text out, never a `Date`.
 * 2. Form values — the `YYYY-MM-DD[ HH:mm:ss]` strings Mantine emits, their
 *    conversion for the API, comparison, and the typed-input parser.
 * 3. Calendar-day anchors — day arithmetic that must not shift with the
 *    viewer's timezone or DST.
 *
 * The timezone-sensitive cases run under several zones on both sides of UTC.
 * They guard the concrete defects this module was written for: `new Date(iso)`
 * read with local accessors reported the previous day west of UTC, ms-based day
 * counts broke across DST, and the calendar week label was off by one (`CW 0`
 * around New Year).
 *
 * **Validates: Requirements 6.4**
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { inEveryTimezone, withTimezone } from '../testUtils/timezone'
import {
  addDaysUtc,
  addMonthsUtc,
  compareDateTimes,
  compareDates,
  dayAnchorFromLocal,
  dayAnchorToIso,
  differenceInDays,
  formatDate,
  formatDateTime,
  isValidAnchor,
  isoWeekNumber,
  parseDisplayDate,
  startOfDayUtc,
  startOfIsoWeekUtc,
  startOfMonthUtc,
  toIsoDate,
  toIsoDateTime,
  todayUtc,
} from './date'

// --- Generators ---

/** Valid `Date` objects within a reasonable range (2000–2099). */
const localDateArb = fc
  .date({ min: new Date(2000, 0, 1), max: new Date(2099, 11, 31) })
  .filter((d) => !Number.isNaN(d.getTime()))

/** Valid ISO date strings (`YYYY-MM-DD`), day capped at 28 to stay valid. */
const isoDateArb = fc
  .tuple(
    fc.integer({ min: 2000, max: 2099 }),
    fc.integer({ min: 1, max: 12 }),
    fc.integer({ min: 1, max: 28 }),
  )
  .map(([y, m, d]) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`)

/** Valid ISO date-time strings (`YYYY-MM-DDTHH:mm`). */
const isoDateTimeArb = fc
  .tuple(isoDateArb, fc.integer({ min: 0, max: 23 }), fc.integer({ min: 0, max: 59 }))
  .map(([date, h, m]) => `${date}T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`)

// ---------------------------------------------------------------------------
// 1. Display formatting
// ---------------------------------------------------------------------------

describe('formatDate', () => {
  it('renders the placeholder for empty input', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate(undefined)).toBe('—')
    expect(formatDate('')).toBe('—')
  })

  it('defaults to German, so existing call sites are unchanged', () => {
    // The locale parameter was added for the callers that know the active locale. Roughly
    // thirty do not pass it, and their output must not move because a parameter appeared.
    expect(formatDate('2026-09-01')).toBe('01.09.2026')
    expect(formatDate('2026-09-01', 'de')).toBe('01.09.2026')
  })

  it('renders ISO for English rather than a slashed form', () => {
    // 01/09/2026 is two different days depending on who reads it. A planning tool showing
    // the wrong day is worse than one showing an unfamiliar order.
    expect(formatDate('2026-09-01', 'en')).toBe('2026-09-01')
    expect(formatDate('2026-12-24T08:30', 'en')).toBe('2026-12-24')
  })

  it('keeps 24-hour time in both locales', () => {
    // Shift boundaries are read off these: 14:00 cannot be misread the way 2:00 can.
    expect(formatDateTime('2026-09-01T14:00', 'de')).toBe('01.09.2026 14:00')
    expect(formatDateTime('2026-09-01T14:00', 'en')).toBe('2026-09-01 14:00')
  })

  it('Property: ISO dates render as DD.MM.YYYY in every timezone', () => {
    inEveryTimezone(() => {
      fc.assert(
        fc.property(isoDateArb, (iso) => {
          const [y, m, d] = iso.split('-')
          expect(formatDate(iso)).toBe(`${d}.${m}.${y}`)
        }),
        { numRuns: 50 },
      )
    })
  })

  it('Property: date-time strings render only their date portion', () => {
    fc.assert(
      fc.property(isoDateTimeArb, (iso) => {
        expect(formatDate(iso)).toBe(formatDate(iso.slice(0, 10)))
      }),
      { numRuns: 100 },
    )
  })

  it('returns non-ISO input unchanged', () => {
    expect(formatDate('not a date')).toBe('not a date')
  })
})

describe('formatDateTime', () => {
  it('renders the placeholder for empty input', () => {
    expect(formatDateTime(null)).toBe('—')
    expect(formatDateTime(undefined)).toBe('—')
  })

  it('Property: renders DD.MM.YYYY HH:mm literally, without timezone shifts', () => {
    inEveryTimezone(() => {
      fc.assert(
        fc.property(isoDateTimeArb, (iso) => {
          const [date, time] = iso.split('T')
          const [y, m, d] = date.split('-')
          expect(formatDateTime(iso)).toBe(`${d}.${m}.${y} ${time}`)
        }),
        { numRuns: 50 },
      )
    })
  })

  it('renders a date-only value at midnight', () => {
    expect(formatDateTime('2026-04-24')).toBe('24.04.2026 00:00')
  })

  it('accepts the space separator used by Mantine date-time values', () => {
    expect(formatDateTime('2026-04-24 16:45:00')).toBe('24.04.2026 16:45')
  })
})

// ---------------------------------------------------------------------------
// 2. Form values
// ---------------------------------------------------------------------------

describe('toIsoDate', () => {
  it('Property: local Date objects keep their calendar day', () => {
    fc.assert(
      fc.property(localDateArb, (date) => {
        const result = toIsoDate(date)
        expect(result).toMatch(/^\d{4}-\d{2}-\d{2}$/)
        const [y, m, d] = result.split('-').map(Number)
        expect([y, m, d]).toEqual([date.getFullYear(), date.getMonth() + 1, date.getDate()])
      }),
      { numRuns: 100 },
    )
  })

  it('Property: ISO date strings pass through unchanged', () => {
    fc.assert(
      fc.property(isoDateArb, (iso) => {
        expect(toIsoDate(iso)).toBe(iso)
      }),
      { numRuns: 100 },
    )
  })

  it('Property: date-time strings keep only the date portion', () => {
    fc.assert(
      fc.property(isoDateTimeArb, (iso) => {
        expect(toIsoDate(iso)).toBe(iso.slice(0, 10))
        // Mantine's DateTimePicker uses a space separator and seconds.
        expect(toIsoDate(`${iso.replace('T', ' ')}:00`)).toBe(iso.slice(0, 10))
      }),
      { numRuns: 100 },
    )
  })

  it('returns an empty string for unparseable input', () => {
    expect(toIsoDate('not a date')).toBe('')
    expect(toIsoDate(new Date('invalid'))).toBe('')
  })
})

describe('toIsoDateTime', () => {
  it('Property: local Date objects keep their wall-clock time', () => {
    fc.assert(
      fc.property(localDateArb, (date) => {
        const result = toIsoDateTime(date)
        expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
        expect(result.startsWith(toIsoDate(date))).toBe(true)
        const [hh, mm] = result.split('T')[1].split(':').map(Number)
        expect([hh, mm]).toEqual([date.getHours(), date.getMinutes()])
      }),
      { numRuns: 100 },
    )
  })

  it('Property: normalises both separators to "T"', () => {
    fc.assert(
      fc.property(isoDateTimeArb, (iso) => {
        expect(toIsoDateTime(iso)).toBe(iso)
        expect(toIsoDateTime(`${iso.replace('T', ' ')}:00`)).toBe(iso)
      }),
      { numRuns: 100 },
    )
  })

  it('turns a date-only value into midnight', () => {
    expect(toIsoDateTime('2026-04-24')).toBe('2026-04-24T00:00')
  })

  it('returns an empty string for unparseable input', () => {
    expect(toIsoDateTime('not a date')).toBe('')
    expect(toIsoDateTime(new Date('invalid'))).toBe('')
  })
})

describe('compareDates / compareDateTimes', () => {
  it('Property: ordering is independent of Date vs string representation', () => {
    fc.assert(
      fc.property(isoDateArb, isoDateArb, (a, b) => {
        const expected = a === b ? 0 : a < b ? -1 : 1
        const dateA = new Date(`${a}T00:00:00`)
        const dateB = new Date(`${b}T00:00:00`)
        expect(compareDates(a, b)).toBe(expected)
        expect(compareDates(dateA, dateB)).toBe(expected)
        // Mixed representations must not silently produce NaN comparisons.
        expect(compareDates(a, dateB)).toBe(expected)
        expect(compareDates(dateA, b)).toBe(expected)
      }),
      { numRuns: 100 },
    )
  })

  it('Property: compareDates ignores the time part', () => {
    fc.assert(
      fc.property(isoDateArb, (day) => {
        expect(compareDates(`${day} 23:59:00`, day)).toBe(0)
      }),
      { numRuns: 100 },
    )
  })

  it('Property: compareDateTimes orders by minute across representations', () => {
    fc.assert(
      fc.property(isoDateTimeArb, isoDateTimeArb, (a, b) => {
        const expected = a === b ? 0 : a < b ? -1 : 1
        expect(compareDateTimes(a, b)).toBe(expected)
        expect(compareDateTimes(new Date(a), b)).toBe(expected)
        expect(compareDateTimes(a, new Date(b))).toBe(expected)
      }),
      { numRuns: 100 },
    )
  })
})

describe('parseDisplayDate', () => {
  it('Property: round-trips the display format in every timezone', () => {
    inEveryTimezone(() => {
      fc.assert(
        fc.property(isoDateArb, (iso) => {
          expect(parseDisplayDate(formatDate(iso))).toBe(iso)
        }),
        { numRuns: 50 },
      )
    })
  })

  it('reads day-first, unlike new Date()', () => {
    // The month-first fallback of `new Date('06.04.2026')` produced June 4th.
    expect(parseDisplayDate('06.04.2026')).toBe('2026-04-06')
    // A day above 12 was rejected entirely by that fallback.
    expect(parseDisplayDate('24.04.2026')).toBe('2026-04-24')
  })

  it('accepts single digits, alternative separators, ISO input and padding', () => {
    expect(parseDisplayDate('6.4.2026')).toBe('2026-04-06')
    expect(parseDisplayDate('24-04-2026')).toBe('2026-04-24')
    expect(parseDisplayDate('24/04/2026')).toBe('2026-04-24')
    expect(parseDisplayDate('2026-04-24')).toBe('2026-04-24')
    expect(parseDisplayDate('  24.04.2026  ')).toBe('2026-04-24')
  })

  it('rejects incomplete, ambiguous and impossible dates', () => {
    expect(parseDisplayDate('')).toBeNull()
    expect(parseDisplayDate('24.04.')).toBeNull()
    expect(parseDisplayDate('24.04.26')).toBeNull() // two-digit year is ambiguous
    expect(parseDisplayDate('31.02.2026')).toBeNull() // February has 28 days in 2026
    expect(parseDisplayDate('00.04.2026')).toBeNull()
    expect(parseDisplayDate('24.13.2026')).toBeNull()
    expect(parseDisplayDate('tomorrow')).toBeNull()
  })

  it('accepts the leap day only in leap years', () => {
    expect(parseDisplayDate('29.02.2028')).toBe('2028-02-29')
    expect(parseDisplayDate('29.02.2026')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// 3. Calendar-day anchors
// ---------------------------------------------------------------------------

describe('startOfDayUtc', () => {
  it('Property: keeps the calendar day of an ISO string in every timezone', () => {
    inEveryTimezone(() => {
      fc.assert(
        fc.property(isoDateArb, (iso) => {
          const anchor = startOfDayUtc(iso)
          expect(dayAnchorToIso(anchor)).toBe(iso)
          expect(anchor.getUTCHours()).toBe(0)
        }),
        { numRuns: 50 },
      )
    })
  })

  it('reports the correct weekday west of UTC, unlike new Date(iso)', () => {
    withTimezone('America/Los_Angeles', () => {
      // 2026-03-02 is a Monday.
      expect(startOfDayUtc('2026-03-02').getUTCDay()).toBe(1)
      // The naive approach reads Sunday: UTC midnight is still Sunday evening
      // in Los Angeles.
      expect(new Date('2026-03-02').getDay()).toBe(0)
    })
  })

  it('marks unparseable input as an invalid anchor', () => {
    expect(isValidAnchor(startOfDayUtc('nonsense'))).toBe(false)
    expect(dayAnchorToIso(startOfDayUtc('nonsense'))).toBe('')
  })
})

describe('dayAnchorFromLocal / todayUtc', () => {
  it('anchors the day a local Date shows the viewer', () => {
    withTimezone('America/Los_Angeles', () => {
      const localEvening = new Date(2026, 2, 2, 23, 30)
      expect(dayAnchorToIso(dayAnchorFromLocal(localEvening))).toBe('2026-03-02')
    })
  })

  it('anchors the viewer’s current calendar day in every timezone', () => {
    inEveryTimezone(() => {
      const now = new Date()
      const anchor = todayUtc()
      expect(anchor.getUTCFullYear()).toBe(now.getFullYear())
      expect(anchor.getUTCMonth()).toBe(now.getMonth())
      expect(anchor.getUTCDate()).toBe(now.getDate())
    })
  })

  it('marks an invalid Date as an invalid anchor', () => {
    expect(isValidAnchor(dayAnchorFromLocal(new Date('invalid')))).toBe(false)
  })
})

describe('addDaysUtc / addMonthsUtc', () => {
  it('Property: shifting forward and back is the identity', () => {
    fc.assert(
      fc.property(isoDateArb, fc.integer({ min: -400, max: 400 }), (iso, days) => {
        const anchor = startOfDayUtc(iso)
        expect(addDaysUtc(addDaysUtc(anchor, days), -days).getTime()).toBe(anchor.getTime())
      }),
      { numRuns: 100 },
    )
  })

  it('crosses a DST switch without losing an hour', () => {
    withTimezone('Europe/Berlin', () => {
      // Germany switches to summer time on 2026-03-29.
      expect(dayAnchorToIso(addDaysUtc(startOfDayUtc('2026-03-28'), 1))).toBe('2026-03-29')
      expect(differenceInDays('2026-03-30', '2026-03-28')).toBe(2)
    })
  })

  it('shifts months on the anchored day', () => {
    expect(dayAnchorToIso(addMonthsUtc(startOfDayUtc('2026-01-01'), 2))).toBe('2026-03-01')
    expect(dayAnchorToIso(addMonthsUtc(startOfDayUtc('2026-12-01'), 1))).toBe('2027-01-01')
  })
})

describe('startOfMonthUtc / startOfIsoWeekUtc', () => {
  it('anchors the first of the month in every timezone', () => {
    inEveryTimezone(() => {
      expect(dayAnchorToIso(startOfMonthUtc(startOfDayUtc('2026-03-17')))).toBe('2026-03-01')
    })
  })

  it('Property: snapping to Monday lands on a Monday within the same week', () => {
    fc.assert(
      fc.property(isoDateArb, (iso) => {
        const day = startOfDayUtc(iso)
        const monday = startOfIsoWeekUtc(day)
        expect(monday.getUTCDay()).toBe(1)
        const offset = differenceInDays(day, monday)
        expect(offset).toBeGreaterThanOrEqual(0)
        expect(offset).toBeLessThanOrEqual(6)
      }),
      { numRuns: 100 },
    )
  })
})

describe('differenceInDays', () => {
  it('Property: matches the difference of the raw day numbers', () => {
    fc.assert(
      fc.property(isoDateArb, isoDateArb, (a, b) => {
        const expected = Math.round(
          (Date.parse(`${a}T00:00:00Z`) - Date.parse(`${b}T00:00:00Z`)) / 86400000,
        )
        expect(differenceInDays(a, b)).toBe(expected)
      }),
      { numRuns: 100 },
    )
  })

  it('Property: is antisymmetric and zero for identical days', () => {
    fc.assert(
      fc.property(isoDateArb, isoDateArb, (a, b) => {
        expect(differenceInDays(a, b)).toBe(-differenceInDays(b, a))
        expect(differenceInDays(a, a)).toBe(0)
      }),
      { numRuns: 100 },
    )
  })

  it('counts inclusive spans as expected', () => {
    expect(differenceInDays('2026-03-02', '2026-03-02') + 1).toBe(1)
    expect(differenceInDays('2026-03-20', '2026-03-02') + 1).toBe(19)
  })

  it('is stable across timezones and accepts anchors', () => {
    inEveryTimezone(() => {
      expect(differenceInDays('2026-07-15', '2026-01-01')).toBe(195)
      expect(differenceInDays(startOfDayUtc('2026-07-15'), '2026-01-01')).toBe(195)
    })
  })

  it('returns 0 when a value is invalid', () => {
    expect(differenceInDays('nonsense', '2026-01-01')).toBe(0)
  })
})

describe('isoWeekNumber', () => {
  it('places the days around New Year in the week of the owning year', () => {
    // 2026-01-01 is a Thursday, so its week (starting 2025-12-29) is CW 1.
    expect(isoWeekNumber('2025-12-29')).toBe(1)
    expect(isoWeekNumber('2026-01-01')).toBe(1)
    expect(isoWeekNumber('2026-01-04')).toBe(1)
    expect(isoWeekNumber('2026-01-05')).toBe(2)
    // 2020 had 53 ISO weeks; 2020-12-28 belongs to the last one.
    expect(isoWeekNumber('2020-12-28')).toBe(53)
    expect(isoWeekNumber('2021-01-04')).toBe(1)
  })

  it('Property: always between 1 and 53', () => {
    fc.assert(
      fc.property(isoDateArb, (iso) => {
        const week = isoWeekNumber(iso)
        expect(week).toBeGreaterThanOrEqual(1)
        expect(week).toBeLessThanOrEqual(53)
      }),
      { numRuns: 200 },
    )
  })

  it('Property: every day of an ISO week shares its number', () => {
    fc.assert(
      fc.property(isoDateArb, (iso) => {
        const monday = startOfIsoWeekUtc(startOfDayUtc(iso))
        const week = isoWeekNumber(monday)
        for (let offset = 0; offset < 7; offset += 1) {
          expect(isoWeekNumber(addDaysUtc(monday, offset))).toBe(week)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('Property: consecutive weeks differ by one, except at a year rollover', () => {
    fc.assert(
      fc.property(isoDateArb, (iso) => {
        const monday = startOfIsoWeekUtc(startOfDayUtc(iso))
        const next = isoWeekNumber(addDaysUtc(monday, 7))
        expect(next === isoWeekNumber(monday) + 1 || next === 1).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('is stable across timezones', () => {
    inEveryTimezone(() => {
      expect(isoWeekNumber('2026-07-27')).toBe(31)
    })
  })

  it('returns 0 for invalid input', () => {
    expect(isoWeekNumber('nonsense')).toBe(0)
  })
})
