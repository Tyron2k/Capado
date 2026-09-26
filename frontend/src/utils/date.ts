/**
 * Central date utilities. Three groups, each with its own value shape — mixing
 * them is what caused the date bugs this module now guards against:
 *
 * 1. **Display formatting** keeps calendar-only dates literal, while UTC
 *    timestamps are rendered in the configured IANA time zone.
 * 2. **Form values** (`DateFormValue`) are what Mantine's date inputs emit:
 *    `YYYY-MM-DD` strings, or `YYYY-MM-DD HH:mm:ss` with a time part. Convert
 *    calendar dates for the API with `toIsoDate`, and local booking times with
 *    `localDateTimeToUtc`. Compare form values with `compareDates` /
 *    `compareDateTimes`.
 * 3. **Calendar-day anchors** (`DayAnchor`) are for day arithmetic: UTC
 *    midnight instants carrying a brand, so a plain `Date` cannot be passed in
 *    by accident. See the section further down for why.
 */

// Type-only import: erased at compile time, so this adds no runtime dependency from the
// date utilities onto the i18n module (which pulls in React and both dictionaries).
import type { Locale } from '../i18n'
import { Temporal } from '@js-temporal/polyfill'

/** Milliseconds in a calendar day (exact, because anchors are UTC-based). */
export const MS_PER_DAY = 86_400_000
/** dayjs display format for dates, shared by all date inputs. */
export const DISPLAY_DATE_FORMAT = 'DD.MM.YYYY'

/** dayjs display format for timestamps, shared by all date-time inputs. */
export const DISPLAY_DATE_TIME_FORMAT = 'DD.MM.YYYY HH:mm'

/** Placeholder rendered for missing or unparseable values. */
const EMPTY = '—'

/** Matches a leading `YYYY-MM-DD`, optionally followed by a time part. */
const ISO_PREFIX = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/

/** Matches a typed date such as `24.04.2026`, `24-4-2026` or `24/04/2026`. */
const TYPED_DATE = /^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$/
const HAS_OFFSET = /(?:Z|[+-]\d{2}:\d{2})$/i
const ZONE_FORMATTERS = new Map<string, Intl.DateTimeFormat>()

/** Calendar and clock parts of an instant in an IANA time zone. */
function zonedParts(instant: Date, timeZone: string): string {
  let formatter = ZONE_FORMATTERS.get(timeZone)
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-GB', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
    ZONE_FORMATTERS.set(timeZone, formatter)
  }
  const parts = formatter.formatToParts(instant)
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? ''
  return `${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}`
}

/** Render an API instant as a date-time form value in the selected zone. */
export function instantToLocalDateTime(value: string, timeZone: string): string {
  if (!HAS_OFFSET.test(value)) return toIsoDateTime(value)
  const instant = new Date(value)
  return Number.isNaN(instant.getTime()) ? '' : zonedParts(instant, timeZone)
}

/**
 * Convert an entered wall-clock time to an unambiguous UTC instant.
 *
 * DST gaps have no matching instant; repeated autumn times have two. Both are
 * rejected rather than silently moving or choosing an arbitrary offset.
 */
export function localDateTimeToUtc(value: Date | string, timeZone: string): string | null {
  try {
    // Preserve an already resolved instant, including its fold and sub-minute precision.
    if (typeof value === 'string' && HAS_OFFSET.test(value)) {
      const instant = Temporal.Instant.from(value)
      return instant.toString({
        fractionalSecondDigits: instant.epochNanoseconds % 1_000_000n === 0n ? 3 : 'auto',
      })
    }
    return Temporal.PlainDateTime.from(toIsoDateTime(value))
      .toZonedDateTime(timeZone, { disambiguation: 'reject' })
      .toInstant()
      .toString({ fractionalSecondDigits: 3 })
  } catch {
    return null
  }
}

/** Explicit choices for an autumn fold; spring gaps have no valid choices. */
export function localTimeChoices(
  value: string,
  timeZone: string,
): { value: string; label: string }[] {
  try {
    const local = Temporal.PlainDateTime.from(instantToLocalDateTime(value, timeZone))
    const candidates = (['earlier', 'later'] as const)
      .map((disambiguation) => local.toZonedDateTime(timeZone, { disambiguation }))
      .filter((candidate) => candidate.toPlainDateTime().equals(local))
    if (
      candidates.length !== 2 ||
      candidates[0].epochNanoseconds === candidates[1].epochNanoseconds
    )
      return []
    return candidates.map((candidate) => ({
      value: candidate.toInstant().toString({ fractionalSecondDigits: 3 }),
      label: `UTC${candidate.offset}`,
    }))
  } catch {
    return []
  }
}

// ---------------------------------------------------------------------------
// 1. Display formatting
// ---------------------------------------------------------------------------

/**
 * Format an ISO date or date-time string for display.
 *
 * Only the date portion is read, so the result never shifts by a day. Returns
 * `—` for empty input and the input itself if it is not ISO-shaped.
 *
 * `Date` values are rejected by the type: a `Date` may be a local instant or a
 * {@link DayAnchor}, and the two format differently. Convert explicitly with
 * `toIsoDate(localDate)` or `dayAnchorToIso(anchor)`.
 *
 * `locale` picks the order, and the ordering is done by REARRANGING the parts
 * already extracted textually — no `Intl.DateTimeFormat`, because that needs a
 * `Date` and constructing one is the whole bug class this module exists to
 * prevent. It defaults to German so the 30-odd existing call sites keep their
 * behaviour; only callers that know the active locale need to pass it.
 *
 * English renders ISO rather than a slashed form on purpose: `01/09/2026` means
 * two different days depending on which side of the Atlantic reads it, and a
 * planning tool showing the wrong day is worse than one showing an unfamiliar
 * order. ISO 8601 is unambiguous, and it needs no month names, so it cannot
 * drift out of step with a translation.
 */
export function formatDate(value?: string | null, locale: Locale = 'de'): string {
  if (!value) return EMPTY
  const match = ISO_PREFIX.exec(value)
  if (!match) return value
  const [, y, m, d] = match
  return locale === 'en' ? `${y}-${m}-${d}` : `${d}.${m}.${y}`
}

/**
 * Format an ISO date-time string for display.
 *
 * Offset-bearing API timestamps are converted into the configured IANA zone.
 * A date-only value renders as `00:00` without conversion.
 * Returns `—` for empty input and the input itself if it is not ISO-shaped.
 *
 * The time part stays 24-hour in both locales: a planning tool reads shift
 * boundaries off these, and 14:00 cannot be misread the way 2:00 can.
 */
export function formatDateTime(
  value?: string | null,
  locale: Locale = 'de',
  timeZone = 'Europe/Berlin',
  showSeconds = false,
): string {
  if (!value) return EMPTY
  const local = instantToLocalDateTime(value, timeZone)
  const match = ISO_PREFIX.exec(local)
  if (!match) return value
  const [, y, m, d, hh, mm] = match
  const seconds = HAS_OFFSET.test(value)
    ? String(new Date(value).getUTCSeconds()).padStart(2, '0')
    : (value.match(/:\d{2}:(\d{2})/)?.[1] ?? '00')
  const time = `${hh ?? '00'}:${mm ?? '00'}${showSeconds ? `:${seconds}` : ''}`
  return locale === 'en' ? `${y}-${m}-${d} ${time}` : `${d}.${m}.${y} ${time}`
}

// ---------------------------------------------------------------------------
// 2. Form values
// ---------------------------------------------------------------------------

/**
 * Value shape emitted by Mantine date inputs (`DateInput`, `DatePickerInput`,
 * `DateTimePicker`): a `YYYY-MM-DD` string, or `YYYY-MM-DD HH:mm:ss` when a
 * time part is present. `Date` objects are accepted as input because state
 * seeded elsewhere may still hold them.
 */
export type DateFormValue = Date | string | null

/**
 * Convert a form value to an ISO date string (`YYYY-MM-DD`) for the API.
 *
 * Accepts both `Date` objects (read in local time) and the
 * `YYYY-MM-DD[ HH:mm:ss]` strings Mantine emits. Returns an empty string for
 * unparseable input so that callers never crash on a malformed value.
 */
export function toIsoDate(value: Date | string): string {
  if (typeof value === 'string') {
    const match = ISO_PREFIX.exec(value)
    if (match) return `${match[1]}-${match[2]}-${match[3]}`
    const parsed = new Date(value)
    return Number.isNaN(parsed.getTime()) ? '' : toIsoDate(parsed)
  }
  if (Number.isNaN(value.getTime())) return ''
  const y = value.getFullYear()
  const m = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/**
 * Convert a form value to an ISO date-time string (`YYYY-MM-DDTHH:mm`).
 *
 * Accepts both `Date` objects (read in local time) and the
 * `YYYY-MM-DD HH:mm:ss` strings Mantine's `DateTimePicker` emits. A date-only
 * value yields midnight. Returns an empty string for unparseable input.
 */
export function toIsoDateTime(value: Date | string): string {
  if (typeof value === 'string') {
    const match = ISO_PREFIX.exec(value)
    if (match) {
      return `${match[1]}-${match[2]}-${match[3]}T${match[4] ?? '00'}:${match[5] ?? '00'}`
    }
    const parsed = new Date(value)
    return Number.isNaN(parsed.getTime()) ? '' : toIsoDateTime(parsed)
  }
  if (Number.isNaN(value.getTime())) return ''
  const hh = String(value.getHours()).padStart(2, '0')
  const mm = String(value.getMinutes()).padStart(2, '0')
  return `${toIsoDate(value)}T${hh}:${mm}`
}

/**
 * Compare two form values by calendar day, ignoring any time part.
 *
 * Mixing a string and a `Date` in a plain `<` comparison silently yields
 * `NaN`-based nonsense, so form validators must use this helper.
 *
 * Returns a negative number if `a` is earlier than `b`, `0` if both fall on the
 * same day, and a positive number if `a` is later.
 */
export function compareDates(a: Date | string, b: Date | string): number {
  const isoA = toIsoDate(a)
  const isoB = toIsoDate(b)
  return isoA === isoB ? 0 : isoA < isoB ? -1 : 1
}

/**
 * Compare two form values with minute precision.
 *
 * Returns a negative number if `a` is earlier than `b`, `0` if both denote the
 * same minute, and a positive number if `a` is later.
 */
export function compareDateTimes(a: Date | string, b: Date | string): number {
  const isoA = toIsoDateTime(a)
  const isoB = toIsoDateTime(b)
  return isoA === isoB ? 0 : isoA < isoB ? -1 : 1
}

/**
 * Parse text typed into a date input into a `YYYY-MM-DD` form value.
 *
 * Accepts `DD.MM.YYYY` (also with `-` or `/` separators and single-digit day or
 * month) plus pasted ISO dates. Rejects anything else, including impossible
 * dates such as `31.02.2026`, by returning `null` — the input then keeps the
 * raw text and the value stays unchanged, which is Mantine's contract for
 * `dateParser`.
 *
 * This exists so the date inputs never depend on dayjs's `customParseFormat`
 * plugin: without it dayjs ignores the format and falls back to `new Date(…)`,
 * which reads `06.04.2026` as June 4th and rejects `24.04.2026` outright.
 */
export function parseDisplayDate(input: string): string | null {
  const text = input.trim()
  if (!text) return null

  let year: number
  let month: number
  let day: number

  const typed = TYPED_DATE.exec(text)
  if (typed) {
    day = Number(typed[1])
    month = Number(typed[2])
    year = Number(typed[3])
  } else {
    const iso = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(text)
    if (!iso) return null
    year = Number(iso[1])
    month = Number(iso[2])
    day = Number(iso[3])
  }

  const candidate = new Date(Date.UTC(year, month - 1, day))
  // Rejects overflow such as 31.02. → 03.03.
  if (
    candidate.getUTCFullYear() !== year ||
    candidate.getUTCMonth() !== month - 1 ||
    candidate.getUTCDate() !== day
  ) {
    return null
  }
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

// ---------------------------------------------------------------------------
// 3. Calendar-day anchors
// ---------------------------------------------------------------------------
//
// The app models calendar days, not instants: a work package running
// `2026-03-02` to `2026-03-20` covers the same days for every viewer. Day math
// therefore happens on UTC midnight anchors, which keeps every day exactly 24 h
// long (no DST gaps) and makes results independent of the viewer's timezone.
//
// The `DayAnchor` brand keeps the two kinds of `Date` apart: a local instant
// cannot be passed where an anchor is expected, and anchors can only be created
// through the constructors below. Read them with the `getUTC*` accessors —
// `getDate()` / `getDay()` would report the previous day west of UTC.

declare const dayAnchorBrand: unique symbol

/** A `Date` pinned to UTC midnight, representing one calendar day. */
export type DayAnchor = Date & { readonly [dayAnchorBrand]: true }

/** Wrap a raw millisecond value known to be UTC midnight. */
function asAnchor(ms: number): DayAnchor {
  return new Date(ms) as DayAnchor
}

/**
 * Anchor the calendar day written in an ISO date or date-time string.
 *
 * Returns an anchor holding `Invalid Date` for unparseable input; callers that
 * care can check it with `isValidAnchor`.
 */
export function startOfDayUtc(iso: string): DayAnchor {
  const match = ISO_PREFIX.exec(iso)
  if (!match) return asAnchor(NaN)
  return asAnchor(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])))
}

/** Anchor the calendar day a local `Date` shows the viewer. */
export function dayAnchorFromLocal(date: Date): DayAnchor {
  if (Number.isNaN(date.getTime())) return asAnchor(NaN)
  return asAnchor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()))
}

/** Anchor the viewer's current calendar day. */
export function todayUtc(): DayAnchor {
  return dayAnchorFromLocal(new Date())
}

/** Whether an anchor represents a real day. */
export function isValidAnchor(anchor: DayAnchor): boolean {
  return !Number.isNaN(anchor.getTime())
}

/** Render an anchor as an ISO date string (`YYYY-MM-DD`). */
export function dayAnchorToIso(anchor: DayAnchor): string {
  if (!isValidAnchor(anchor)) return ''
  const y = anchor.getUTCFullYear()
  const m = String(anchor.getUTCMonth() + 1).padStart(2, '0')
  const d = String(anchor.getUTCDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/** Shift an anchor by whole days (may be negative). */
export function addDaysUtc(anchor: DayAnchor, days: number): DayAnchor {
  return asAnchor(anchor.getTime() + days * MS_PER_DAY)
}

/** Anchor the first day of the anchor's month. */
export function startOfMonthUtc(anchor: DayAnchor): DayAnchor {
  return asAnchor(Date.UTC(anchor.getUTCFullYear(), anchor.getUTCMonth(), 1))
}

/** Shift an anchor by whole months, keeping the day of month where possible. */
export function addMonthsUtc(anchor: DayAnchor, months: number): DayAnchor {
  const shifted = new Date(anchor.getTime())
  shifted.setUTCMonth(shifted.getUTCMonth() + months)
  return shifted as DayAnchor
}

/** Anchor the Monday of the anchor's ISO week. */
export function startOfIsoWeekUtc(anchor: DayAnchor): DayAnchor {
  return addDaysUtc(anchor, -((anchor.getUTCDay() + 6) % 7))
}

/** Accepts either an anchor or an ISO date string. */
type DayLike = DayAnchor | string

function toAnchor(value: DayLike): DayAnchor {
  return typeof value === 'string' ? startOfDayUtc(value) : value
}

/**
 * Whole calendar days from `earlier` to `later` (negative if `later` is before).
 *
 * Exact and unaffected by DST or the viewer's timezone. An inclusive span
 * (`2026-03-02`–`2026-03-02` counts as one day) is
 * `differenceInDays(end, start) + 1`. Returns `0` if either value is invalid.
 */
export function differenceInDays(later: DayLike, earlier: DayLike): number {
  const a = toAnchor(later).getTime()
  const b = toAnchor(earlier).getTime()
  if (Number.isNaN(a) || Number.isNaN(b)) return 0
  return Math.round((a - b) / MS_PER_DAY)
}

/**
 * ISO 8601 calendar week number (1–53) of a calendar day.
 *
 * Weeks start on Monday and week 1 is the week containing January 4th, so days
 * around New Year belong to the week of the adjacent year where applicable
 * (`2026-01-01` is CW 1, `2020-12-28` is CW 53). Returns `0` for invalid input.
 */
export function isoWeekNumber(value: DayLike): number {
  const day = toAnchor(value)
  if (!isValidAnchor(day)) return 0
  // The Thursday of a week determines which year owns that week.
  const thursday = addDaysUtc(day, 3 - ((day.getUTCDay() + 6) % 7))
  const week1Anchor = Date.UTC(thursday.getUTCFullYear(), 0, 4)
  return Math.round((thursday.getTime() - week1Anchor) / MS_PER_DAY / 7) + 1
}
