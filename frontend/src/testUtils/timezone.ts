/**
 * Timezone helpers for tests.
 *
 * Date logic must behave identically for viewers east and west of UTC, so the
 * relevant tests run their assertions under several zones. Node re-reads
 * `process.env.TZ` on the next `Date` operation, which makes this possible
 * without spawning separate processes.
 */

/** Zones on both sides of UTC, including one with a half-hour offset. */
const TEST_TIMEZONES = ['Europe/Berlin', 'America/Los_Angeles', 'Asia/Kolkata', 'UTC'] as const

/** Run `body` with `tz` active, restoring the previous zone afterwards. */
export function withTimezone(tz: string, body: () => void): void {
  const previous = process.env.TZ
  process.env.TZ = tz
  try {
    body()
  } finally {
    process.env.TZ = previous
  }
}

/** Run `body` once per {@link TEST_TIMEZONES} entry. */
export function inEveryTimezone(body: (tz: string) => void): void {
  for (const tz of TEST_TIMEZONES) {
    withTimezone(tz, () => body(tz))
  }
}
