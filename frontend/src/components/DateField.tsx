/**
 * Project-wide date input wrappers.
 *
 * All date entry goes through these instead of Mantine's `DateInput` /
 * `DateTimePicker` directly, so two things hold everywhere:
 *
 * - The display format is the same (`DD.MM.YYYY`, `DD.MM.YYYY HH:mm`).
 * - Typed text is parsed by {@link parseDisplayDate}, our own tested parser.
 *   Mantine would otherwise parse with `dayjs(text, valueFormat)`, which
 *   silently falls back to `new Date(text)` unless dayjs's `customParseFormat`
 *   plugin happens to be registered — a global side effect that is easy to lose
 *   and fails quietly (`06.04.2026` became June 4th, `24.04.2026` was dropped).
 *
 * Both components emit `YYYY-MM-DD` / `YYYY-MM-DD HH:mm:ss` **strings** via
 * `onChange`, like the Mantine components they wrap. Use `DateFormValue` for the
 * surrounding state.
 */

import { DateInput, DateTimePicker } from '@mantine/dates'
import type { DateInputProps, DateTimePickerProps } from '@mantine/dates'
import { DISPLAY_DATE_FORMAT, DISPLAY_DATE_TIME_FORMAT, parseDisplayDate } from '../utils/date'

type DateFieldProps = Omit<DateInputProps, 'valueFormat' | 'dateParser'>

/**
 * Date input with the project display format and parser.
 * Accepts typed input as well as picking from the dropdown calendar.
 */
export function DateField(props: DateFieldProps) {
  return <DateInput valueFormat={DISPLAY_DATE_FORMAT} dateParser={parseDisplayDate} {...props} />
}

type DateTimeFieldProps = Omit<DateTimePickerProps, 'valueFormat'>

/**
 * Timestamp input (date plus minute-precision time) with the project display
 * format. The visible field is read-only; values are picked in the dropdown, so
 * no text parsing is involved.
 */
export function DateTimeField(props: DateTimeFieldProps) {
  return <DateTimePicker valueFormat={DISPLAY_DATE_TIME_FORMAT} {...props} />
}
