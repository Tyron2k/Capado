# Date Handling Reference (Frontend)

Dates in this app come in three shapes. Mixing them caused every date defect so
far: a crash when saving a work package's time range, typed dates parsed as the
wrong day, calendar days that shifted for viewers west of UTC, and Gantt week
labels that were off by one.

| Shape | Type | Used for |
|-------|------|----------|
| ISO string | `string` (`YYYY-MM-DD`, offset-bearing timestamp) | API payloads, display |
| Form value | `DateFormValue` (`Date \| string \| null`) | what date inputs hold |
| Day anchor | `DayAnchor` (branded `Date` at UTC midnight) | calendar-day arithmetic |

All helpers live in `frontend/src/utils/date.ts`, grouped in that order.

## 1. Use `DateField` / `DateTimeField`, not Mantine's inputs directly

`frontend/src/components/DateField.tsx` wraps `DateInput` and `DateTimePicker`
with the shared display format and, for typed input, our own parser
(`parseDisplayDate`).

```tsx
import { DateField, DateTimeField } from '../../components/DateField'

<DateField label={t('workPackageForm.startDate')} required {...form.getInputProps('start_date')} />
<DateTimeField label={t('assignmentForm.occupiedFrom')} required {...form.getInputProps('start_at')} />
```

Why the wrapper exists: Mantine parses typed text with
`dayjs(text, valueFormat)`. Without dayjs's `customParseFormat` plugin, dayjs
ignores the format and falls back to `new Date(text)` — `06.04.2026` becomes
June 4th and `24.04.2026` is discarded while the typed text stays on screen.
Registering the plugin would work, but it is a global side effect that fails
silently when the import is lost. Passing an explicit `dateParser` removes the
dependency and makes parsing unit-testable.

## 2. Date inputs emit strings

Their `onChange` never returns a `Date`:

| Component | `onChange` payload |
|-----------|--------------------|
| `DateField` / `DateInput` | `YYYY-MM-DD` |
| `DatePickerInput` | `YYYY-MM-DD` |
| `DateTimeField` / `DateTimePicker` | `YYYY-MM-DD HH:mm:ss` |
| `ZonedDateTimeField` (bookings) | UTC instant when resolved; local string while invalid/ambiguous |

Consequences:

- Type form state as `DateFormValue`, never `Date | null`. TypeScript cannot
  catch this on its own, because `form.getInputProps()` is loosely typed.
- Never compare two values with `<` / `>`. Mixing a string and a `Date` coerces
  to `NaN`, so the comparison is always `false` and validation silently passes.
  Use `compareDates` for calendar dates. Compare booking instants after UTC
  conversion: local clock readings can run backwards during an autumn transition.
- Convert calendar-only values with `toIsoDate`. `toIsoDateTime` normalizes a
  *local form value*; it is not an API timestamp. Infrastructure bookings must
  use `localDateTimeToUtc(value, settings.timeZone)` before sending them.

```tsx
const form = useForm<{ start_date: DateFormValue; end_date: DateFormValue }>({
  validate: {
    end_date: (value, values) => {
      if (!value) return t('…endDateRequired')
      if (values.start_date && compareDates(value, values.start_date) < 0) {
        return t('…endDateAfterStart')
      }
      return null
    },
  },
})

form.setValues({ start_date: toIsoDate(workPackage.start_date) }) // seed from API
await updateWorkPackage(projectId, id, { start_date: toIsoDate(values.start_date!) })
```

## 3. Day arithmetic runs on `DayAnchor`, never on `new Date('YYYY-MM-DD')`

`new Date('2026-03-02')` is UTC midnight. Reading it with local accessors
(`getDate`, `getDay`, `getMonth`) reports the previous day for every viewer west
of UTC. Anchoring on *local* midnight instead breaks arithmetic across DST,
where a day is 23 or 25 hours long.

A `DayAnchor` is a `Date` pinned to UTC midnight and carrying a brand, so a plain
`Date` cannot be passed in by accident. Anchors can only be produced by:

| Constructor | Input |
|-------------|-------|
| `startOfDayUtc(iso)` | ISO date or date-time string |
| `dayAnchorFromLocal(date)` | local `Date`, e.g. from a picker |
| `todayUtc()` | the viewer's current day |

and derived with `addDaysUtc`, `addMonthsUtc`, `startOfMonthUtc`,
`startOfIsoWeekUtc`. Read them with `getUTC*`, render them with
`dayAnchorToIso`, and measure with `differenceInDays` / `isoWeekNumber`
(both also accept ISO strings).

```ts
const start = startOfDayUtc(workPackage.start_date)
start.getUTCDay()                                            // weekday, never getDay()
differenceInDays(workPackage.end_date, workPackage.start_date) + 1  // inclusive span
differenceInDays(project.next_deadline, todayUtc())          // days until deadline
isoWeekNumber(week.week_start)                               // CW label
```

`frontend/src/features/gantt/timeAxis.ts` follows this throughout: slot anchors,
labels, `formatIsoDate`, `isCurrentSlot`, and `computeBarGeometry` — shared by every
Gantt perspective and by the projects overview — all work on anchors.

## 4. Calendar dates remain literal; booking instants use the configured zone

`formatDate` reads only the literal `YYYY-MM-DD` calendar date; a time-zone
change must never move a project deadline or a person's date-only assignment.
`formatDateTime` instead converts an offset-bearing UTC booking instant into the
globally configured IANA zone. Pass `settings.timeZone` explicitly at rendering
sites. `ZonedDateTimeField` renders the instant locally but retains it in form
state, preserving which occurrence of a repeated autumn time it represents.
`localDateTimeToUtc` uses `@js-temporal/polyfill` to resolve new wall-clock input;
it rejects spring gaps and unresolved autumn folds. The field offers both UTC
offsets for a fold, requiring an explicit choice. Existing resolved values are
not reinterpreted. Open booking forms pin their input zone and display its name,
so a settings refresh cannot reinterpret an unfinished draft.

Planning rules remain in `Europe/Berlin`, independently of this display setting.
Calendar dates and recurring local availability windows are not UTC instants.
Infrastructure conflict suggestions are calculated in the backend and carry
both `new_start_at` and `new_end_at` as UTC instants. The client applies these
exact values without repeating calendar arithmetic in its display zone.

Display ordering is still textual; the instant-to-local-clock conversion uses
`Intl.DateTimeFormat` with an explicit IANA zone, never the browser's default.

`locale` defaults to `'de'`, so a caller that does not pass one keeps rendering German
dates. Which callers pass it, and why the migration stops where it does, is recorded in
[known limitations](known-limitations.md) rather than here — a count of call sites in a
reference page goes quietly wrong the moment somebody converts one.

English renders ISO rather than a slashed form, on purpose: `01/09/2026` means two
different days depending on who reads it, and a planning tool showing the wrong day
is worse than one showing an unfamiliar order. ISO 8601 is unambiguous and needs no
month names, so it cannot drift out of step with a translation. Times stay 24-hour in
both locales, because shift boundaries are read off them and `14:00` cannot be
misread the way `2:00` can.

## Helper overview

| Function | Purpose |
|----------|---------|
| `formatDate(iso, locale?)` | Display as `DD.MM.YYYY`, or ISO for `'en'`; `—` when empty |
| `formatDateTime(instant, locale?, timeZone?)` | Render a UTC instant in the chosen zone |
| `toIsoDate(value)` | Payload `YYYY-MM-DD` (local time for `Date` input) |
| `toIsoDateTime(value)` | Normalize local form value `YYYY-MM-DDTHH:mm` |
| `instantToLocalDateTime(instant, zone)` | Seed a date-time form from UTC API data |
| `localDateTimeToUtc(value, zone)` | Entered local time to UTC, or `null` at a DST gap/fold |
| `compareDates(a, b)` | Order by calendar day, ignoring any time part |
| `compareDateTimes(a, b)` | Order with minute precision |
| `parseDisplayDate(text)` | Parse typed `DD.MM.YYYY` into `YYYY-MM-DD` |
| `startOfDayUtc(iso)` | Anchor a calendar day |
| `dayAnchorFromLocal(date)` | Anchor the day a local `Date` shows |
| `todayUtc()` | Anchor the viewer's current day |
| `addDaysUtc` / `addMonthsUtc` | Shift an anchor (DST-proof) |
| `startOfMonthUtc` / `startOfIsoWeekUtc` | Snap an anchor |
| `dayAnchorToIso(anchor)` | Render an anchor as `YYYY-MM-DD` |
| `differenceInDays(later, earlier)` | Whole days between two days |
| `isoWeekNumber(value)` | ISO 8601 calendar week (1–53) |
| `MS_PER_DAY` | 86 400 000, the single definition |

## Tests

Timezone-sensitive behaviour is covered under several zones on both sides of UTC
via `src/testUtils/timezone.ts` (`inEveryTimezone`, `withTimezone`), which
reassigns `process.env.TZ`; Node re-reads it on the next `Date` operation. New
date logic must be covered the same way rather than only in the developer's local
zone. See `src/utils/date.test.ts` and `src/features/gantt/timeAxis.test.ts`.

Component-level tests that render date inputs need `<MantineProvider env="test">`
so dropdowns and popovers mount without transitions. Note that Mantine's
`DateTimePicker` shows its value as button text and leaves the underlying
`required` input empty, which makes jsdom's native constraint validation refuse a
click on the submit button — dispatch `submit` on the form instead (see
`AssignmentForm.test.tsx`).
