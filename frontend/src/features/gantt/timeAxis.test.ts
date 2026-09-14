/**
 * Tests for the Gantt time axis.
 *
 * The axis is built from `DayAnchor` values (UTC midnight) so that slot labels,
 * "today" highlighting, and bar geometry describe the same calendar days for
 * every viewer. Previously the anchors were parsed as UTC but read with local
 * accessors, which shifted labels by a day west of UTC, and the calendar week
 * label used a formula that returned `CW 0` around New Year and was off by one
 * for the rest of the year.
 *
 * All fixtures are inline and fictional.
 */

import { describe, it, expect } from 'vitest'
import {
  computeBarGeometry,
  computeTimeAxis,
  formatIsoDate,
  getSlotWidth,
  getTimeSpanEnd,
  isCurrentSlot,
  type TimeAxisItem,
} from './timeAxis'
import {
  addDaysUtc,
  startOfDayUtc,
  startOfIsoWeekUtc,
  startOfMonthUtc,
  todayUtc,
} from '../../utils/date'
import { inEveryTimezone, withTimezone } from '../../testUtils/timezone'

const items: TimeAxisItem[] = [
  { start_date: '2026-03-02', end_date: '2026-03-06' },
  { start_date: '2026-03-09', end_date: '2026-03-13' },
]

describe('computeTimeAxis — day scale', () => {
  it('anchors the axis one padding day before the earliest item', () => {
    inEveryTimezone(() => {
      const { minDate, timeSlots, totalDays } = computeTimeAxis(items, 'day')
      expect(formatIsoDate(minDate)).toBe('2026-03-01')
      expect(formatIsoDate(timeSlots[0].start)).toBe('2026-03-01')
      // 2026-03-01 .. 2026-03-14 inclusive
      expect(timeSlots).toHaveLength(14)
      expect(formatIsoDate(timeSlots[timeSlots.length - 1].start)).toBe('2026-03-14')
      expect(totalDays).toBe(13)
    })
  })

  it('labels slots with the calendar day they represent', () => {
    inEveryTimezone(() => {
      const { timeSlots } = computeTimeAxis(items, 'day')
      expect(timeSlots[0].label).toBe('1.3')
      expect(timeSlots[1].label).toBe('2.3')
    })
  })

  it('keeps 24 h between slots across a DST switch', () => {
    withTimezone('Europe/Berlin', () => {
      // Germany switches to summer time on 2026-03-29.
      const { timeSlots } = computeTimeAxis(
        [{ start_date: '2026-03-28', end_date: '2026-03-31' }],
        'day',
      )
      expect(timeSlots.map((slot) => formatIsoDate(slot.start))).toEqual([
        '2026-03-27',
        '2026-03-28',
        '2026-03-29',
        '2026-03-30',
        '2026-03-31',
        '2026-04-01',
      ])
    })
  })

  it('spans exactly one day past the last slot', () => {
    const { timeSlots } = computeTimeAxis(items, 'day')
    expect(formatIsoDate(getTimeSpanEnd(timeSlots, 'day'))).toBe('2026-03-15')
  })
})

describe('computeTimeAxis — week scale', () => {
  it('snaps slots to Mondays and labels them with the ISO week', () => {
    inEveryTimezone(() => {
      const { timeSlots } = computeTimeAxis(items, 'week')
      // 2026-03-02 minus 3 padding days is 2026-02-27 (Friday) → Monday 2026-02-23.
      expect(formatIsoDate(timeSlots[0].start)).toBe('2026-02-23')
      expect(timeSlots.map((slot) => slot.label)).toEqual(['CW 9', 'CW 10', 'CW 11', 'CW 12'])
      for (const slot of timeSlots) {
        expect(slot.start.getUTCDay()).toBe(1)
      }
    })
  })

  it('labels the week around New Year as CW 1, not CW 0', () => {
    const { timeSlots } = computeTimeAxis(
      [{ start_date: '2026-01-01', end_date: '2026-01-02' }],
      'week',
    )
    expect(timeSlots[0].label).toBe('CW 1')
    expect(timeSlots.map((slot) => slot.label)).not.toContain('CW 0')
  })
})

describe('computeTimeAxis — month scale', () => {
  it('starts each slot on the first of the month', () => {
    inEveryTimezone(() => {
      const { timeSlots } = computeTimeAxis(
        [{ start_date: '2026-01-15', end_date: '2026-03-10' }],
        'month',
      )
      expect(timeSlots.map((slot) => formatIsoDate(slot.start))).toEqual([
        '2026-01-01',
        '2026-02-01',
        '2026-03-01',
      ])
      expect(timeSlots.map((slot) => slot.label)).toEqual(['Jan 2026', 'Feb 2026', 'Mar 2026'])
    })
  })

  it('does not slip into the previous month west of UTC', () => {
    withTimezone('America/Los_Angeles', () => {
      const { timeSlots } = computeTimeAxis(
        [{ start_date: '2026-02-01', end_date: '2026-02-20' }],
        'month',
      )
      // Padding pushes the axis start into January, but not December.
      expect(formatIsoDate(timeSlots[0].start)).toBe('2026-01-01')
    })
  })
})

describe('isCurrentSlot', () => {
  it('marks the slot of the local current day', () => {
    inEveryTimezone(() => {
      expect(isCurrentSlot({ label: 'today', start: todayUtc() }, 'day')).toBe(true)
      expect(isCurrentSlot({ label: 'other', start: startOfDayUtc('2000-01-01') }, 'day')).toBe(
        false,
      )
    })
  })

  it('marks the week slot whose Monday starts the current week', () => {
    inEveryTimezone(() => {
      const monday = startOfIsoWeekUtc(todayUtc())
      expect(isCurrentSlot({ label: 'cw', start: monday }, 'week')).toBe(true)
      expect(isCurrentSlot({ label: 'previous', start: addDaysUtc(monday, -7) }, 'week')).toBe(
        false,
      )
      expect(isCurrentSlot({ label: 'next', start: addDaysUtc(monday, 7) }, 'week')).toBe(false)
    })
  })

  it('marks the month slot containing today', () => {
    inEveryTimezone(() => {
      const thisMonth = startOfMonthUtc(todayUtc())
      expect(isCurrentSlot({ label: 'month', start: thisMonth }, 'month')).toBe(true)
      expect(isCurrentSlot({ label: 'other', start: startOfDayUtc('2000-06-01') }, 'month')).toBe(
        false,
      )
    })
  })
})

describe('computeTimeAxis — empty input', () => {
  it('returns an empty axis anchored on today', () => {
    const { timeSlots, totalDays, minDate } = computeTimeAxis([], 'day')
    expect(timeSlots).toEqual([])
    expect(totalDays).toBe(0)
    expect(minDate.getTime()).toBe(todayUtc().getTime())
  })
})

describe('computeBarGeometry', () => {
  const axis = computeTimeAxis(items, 'day')
  const slotWidth = getSlotWidth('day')

  it('places a bar on its slot boundary and sizes it by inclusive days', () => {
    inEveryTimezone(() => {
      const geometry = computeBarGeometry(items[0], axis, 'day')
      // Axis starts 2026-03-01, bar starts 2026-03-02 → one slot in.
      expect(geometry.leftPx).toBeCloseTo(slotWidth, 6)
      // 2026-03-02 .. 2026-03-06 inclusive is five days.
      expect(geometry.widthPx).toBeCloseTo(5 * slotWidth, 6)
    })
  })

  it('gives a single-day bar exactly one slot', () => {
    const geometry = computeBarGeometry(
      { start_date: '2026-03-05', end_date: '2026-03-05' },
      axis,
      'day',
    )
    expect(geometry.widthPx).toBeCloseTo(slotWidth, 6)
  })

  it('never renders a bar thinner than 4 px', () => {
    const wideAxis = computeTimeAxis(
      [{ start_date: '2020-01-01', end_date: '2030-01-01' }],
      'month',
    )
    const geometry = computeBarGeometry(
      { start_date: '2025-06-01', end_date: '2025-06-01' },
      wideAxis,
      'month',
    )
    expect(geometry.widthPx).toBeGreaterThanOrEqual(4)
  })

  it('returns a neutral geometry for an empty axis', () => {
    const emptyAxis = computeTimeAxis([], 'day')
    expect(computeBarGeometry(items[0], emptyAxis, 'day')).toEqual({ leftPx: 0, widthPx: 4 })
  })

  it('is identical for both Gantt perspectives (same inputs, same output)', () => {
    const projectBar = { start_date: '2026-03-09', end_date: '2026-03-13' }
    const resourceBar = { ...projectBar, has_conflict: true, name: 'Bar' }
    expect(computeBarGeometry(resourceBar, axis, 'day')).toEqual(
      computeBarGeometry(projectBar, axis, 'day'),
    )
  })
})
