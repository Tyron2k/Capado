/**
 * Shared time-axis utilities for all Gantt chart perspectives (project
 * and resource). Keeps the time-axis math isolated from React components.
 *
 * Every date here is a `DayAnchor` — a UTC midnight instant standing for one
 * calendar day (see the calendar-day section of `utils/date`). Slots are
 * therefore exactly 24 h apart regardless of DST, and the axis shows the same
 * days to every viewer. Anchors are read with `getUTC*` accessors only; the
 * brand on `DayAnchor` keeps local `Date` values out.
 */

import {
  MS_PER_DAY,
  addDaysUtc,
  addMonthsUtc,
  isoWeekNumber,
  startOfDayUtc,
  startOfIsoWeekUtc,
  startOfMonthUtc,
  todayUtc,
  type DayAnchor,
} from '../../utils/date'

/** Supported granularity levels for the Gantt time axis. */
export type TimeScale = 'day' | 'week' | 'month'

/** A single slot in the time axis header. */
export interface TimeSlot {
  label: string
  start: DayAnchor
}

/** Minimal item shape required by computeTimeAxis. */
export interface TimeAxisItem {
  start_date: string
  end_date: string
}

/** The computed axis: header slots plus the anchors bars are placed against. */
interface TimeAxis {
  timeSlots: TimeSlot[]
  minDate: DayAnchor
  totalDays: number
}

/** Returns the pixel width of a single time slot for the given scale. */
export function getSlotWidth(timeScale: TimeScale): number {
  switch (timeScale) {
    case 'day':
      return 40
    case 'week':
      return 80
    case 'month':
      return 120
  }
}

/** Padding added on both ends of the axis, in days, per scale. */
function paddingDays(timeScale: TimeScale): number {
  switch (timeScale) {
    case 'day':
      return 1
    case 'week':
      return 3
    case 'month':
      return 7
  }
}

/**
 * Compute the time axis (slots, min date, total days) from a list of items
 * that each have `start_date` and `end_date` ISO date strings.
 *
 * Works with both `GanttWorkPackageBar` and `ResourceGanttBar` — any object
 * satisfying the `TimeAxisItem` interface. With no items the axis is empty and
 * anchored on today.
 */
export function computeTimeAxis(
  items: TimeAxisItem[],
  timeScale: TimeScale,
  /**
   * Prefix for a calendar-week column, e.g. "KW" in German and "CW" in English.
   *
   * Passed in rather than looked up here because this module is pure — it has no access to the i18n
   * hook, and reaching for one would turn a testable function into a component-bound one. The default
   * keeps every existing caller and test valid, and it is the ENGLISH form on purpose: a German
   * default would be wrong for half the installations and right by accident for the other half.
   *
   * This was hardcoded to "CW" for both locales, which put an English abbreviation directly above a
   * control row that had just been translated.
   */
  weekPrefix = 'CW',
): TimeAxis {
  if (items.length === 0) {
    return { timeSlots: [], minDate: todayUtc(), totalDays: 0 }
  }

  let minDate = startOfDayUtc(items[0].start_date)
  let maxDate = startOfDayUtc(items[0].end_date)

  for (const item of items) {
    const start = startOfDayUtc(item.start_date)
    const end = startOfDayUtc(item.end_date)
    if (start < minDate) minDate = start
    if (end > maxDate) maxDate = end
  }

  const padding = paddingDays(timeScale)
  minDate = addDaysUtc(minDate, -padding)
  maxDate = addDaysUtc(maxDate, padding)

  const totalDays = Math.round((maxDate.getTime() - minDate.getTime()) / MS_PER_DAY)
  const timeSlots: TimeSlot[] = []

  switch (timeScale) {
    case 'day':
      for (let day = minDate; day <= maxDate; day = addDaysUtc(day, 1)) {
        timeSlots.push({ label: formatDay(day), start: day })
      }
      break
    case 'week':
      for (
        let monday = startOfIsoWeekUtc(minDate);
        monday <= maxDate;
        monday = addDaysUtc(monday, 7)
      ) {
        timeSlots.push({ label: `${weekPrefix} ${isoWeekNumber(monday)}`, start: monday })
      }
      break
    case 'month':
      for (let month = startOfMonthUtc(minDate); month <= maxDate; month = addMonthsUtc(month, 1)) {
        timeSlots.push({ label: formatMonth(month), start: month })
      }
      break
  }

  return { timeSlots, minDate, totalDays }
}

/** Compute the end of the last time slot (exclusive). */
export function getTimeSpanEnd(timeSlots: TimeSlot[], timeScale: TimeScale): DayAnchor {
  if (timeSlots.length === 0) return todayUtc()
  const lastSlot = timeSlots[timeSlots.length - 1].start
  switch (timeScale) {
    case 'day':
      return addDaysUtc(lastSlot, 1)
    case 'week':
      return addDaysUtc(lastSlot, 7)
    case 'month':
      return addMonthsUtc(lastSlot, 1)
  }
}

/** Pixel placement of a bar on the axis. */
interface BarGeometry {
  leftPx: number
  widthPx: number
}

/**
 * Compute where a bar covering `[start_date, end_date]` sits on the axis.
 *
 * Both perspectives (project and resource Gantt) render identical geometry, so
 * the math lives here where it is unit-testable. The end day is inclusive, and
 * bars are at least 4 px wide so single-day items stay visible.
 */
export function computeBarGeometry(
  item: TimeAxisItem,
  axis: Pick<TimeAxis, 'minDate' | 'timeSlots'>,
  timeScale: TimeScale,
): BarGeometry {
  const { minDate, timeSlots } = axis
  const totalWidth = timeSlots.length * getSlotWidth(timeScale)
  const totalSpanMs = getTimeSpanEnd(timeSlots, timeScale).getTime() - minDate.getTime()
  if (totalSpanMs <= 0) return { leftPx: 0, widthPx: 4 }

  const barStart = startOfDayUtc(item.start_date)
  const barEnd = startOfDayUtc(item.end_date)
  const offsetMs = barStart.getTime() - minDate.getTime()
  const durationMs = barEnd.getTime() - barStart.getTime() + MS_PER_DAY // include end day

  return {
    leftPx: (offsetMs / totalSpanMs) * totalWidth,
    widthPx: Math.max((durationMs / totalSpanMs) * totalWidth, 4),
  }
}

function formatDay(day: DayAnchor): string {
  return `${day.getUTCDate()}.${day.getUTCMonth() + 1}`
}

function formatMonth(month: DayAnchor): string {
  const months = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ]
  return `${months[month.getUTCMonth()]} ${month.getUTCFullYear()}`
}

/**
 * Format a slot anchor as an ISO date string (`YYYY-MM-DD`).
 *
 * Alias of `dayAnchorToIso` under the name the Gantt components use for their
 * `data-testid` values.
 */
export { dayAnchorToIso as formatIsoDate } from '../../utils/date'

/**
 * Determine whether a time slot contains the current date, based on the
 * active time scale. Used to highlight "today" in the Gantt chart.
 */
export function isCurrentSlot(slot: TimeSlot, timeScale: TimeScale): boolean {
  const today = todayUtc()
  const slotStart = slot.start

  switch (timeScale) {
    case 'day':
      return slotStart.getTime() === today.getTime()
    case 'week':
      return today >= slotStart && today <= addDaysUtc(slotStart, 6)
    case 'month':
      return (
        slotStart.getUTCFullYear() === today.getUTCFullYear() &&
        slotStart.getUTCMonth() === today.getUTCMonth()
      )
  }
}
