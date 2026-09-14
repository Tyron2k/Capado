/**
 * Tests for the working-time formatting helpers.
 *
 * These encode two rules that are easy to get wrong and silent when wrong: half
 * hours must survive the round-trip through the UI, because shift patterns use
 * them and rounding a 7.5-hour day to 8 overstates capacity; and a window whose
 * end is not after its start runs past midnight, which is how a night shift is
 * expressed as one row rather than two.
 *
 * All fixtures are inline and fictional.
 */

import { describe, it, expect } from 'vitest'
import { formatMinutes, parseMinutes, wrapsPastMidnight } from './calendar'

describe('formatMinutes', () => {
  it('renders whole hours', () => {
    expect(formatMinutes(480)).toBe('8:00')
  })

  it('renders half hours rather than rounding them away', () => {
    // A 7.5-hour day shown as "8:00" would overstate capacity by 30 minutes for
    // every such resource, every day.
    expect(formatMinutes(450)).toBe('7:30')
  })

  it('pads single-digit minutes', () => {
    expect(formatMinutes(485)).toBe('8:05')
  })

  it('renders zero as a free day', () => {
    expect(formatMinutes(0)).toBe('0:00')
  })

  it('renders a full day', () => {
    expect(formatMinutes(1440)).toBe('24:00')
  })
})

describe('parseMinutes', () => {
  it('parses H:MM', () => {
    expect(parseMinutes('8:00')).toBe(480)
    expect(parseMinutes('7:30')).toBe(450)
  })

  it('parses bare hours', () => {
    expect(parseMinutes('8')).toBe(480)
  })

  it('tolerates surrounding whitespace', () => {
    expect(parseMinutes('  7:30  ')).toBe(450)
  })

  it('rejects an empty value rather than reading it as zero', () => {
    // Zero is a meaningful entry — a free day — so an empty field must not be
    // silently accepted as one.
    expect(parseMinutes('')).toBeNull()
    expect(parseMinutes('   ')).toBeNull()
  })

  it('rejects minutes above 59', () => {
    expect(parseMinutes('8:60')).toBeNull()
    expect(parseMinutes('8:99')).toBeNull()
  })

  it('rejects anything beyond a full day', () => {
    expect(parseMinutes('24:01')).toBeNull()
    expect(parseMinutes('25:00')).toBeNull()
  })

  it('rejects non-numeric input', () => {
    expect(parseMinutes('acht')).toBeNull()
    expect(parseMinutes('8h')).toBeNull()
    expect(parseMinutes('-1')).toBeNull()
  })

  it('round-trips with formatMinutes', () => {
    for (const minutes of [0, 30, 450, 480, 510, 1440]) {
      expect(parseMinutes(formatMinutes(minutes))).toBe(minutes)
    }
  })
})

describe('wrapsPastMidnight', () => {
  it('is false for an ordinary day shift', () => {
    expect(wrapsPastMidnight('06:00', '14:00')).toBe(false)
  })

  it('is true for a night shift', () => {
    // 22:00–06:00 is one row, not two: the tail after midnight belongs to the
    // shift that started the evening before.
    expect(wrapsPastMidnight('22:00', '06:00')).toBe(true)
  })

  it('treats equal times as wrapping, which the backend rejects', () => {
    // Equal times are ambiguous — "no time" or "the whole day" — so the API
    // refuses them. The helper reports them as wrapping so a form can flag the
    // row rather than rendering an interval that reads backwards.
    expect(wrapsPastMidnight('06:00', '06:00')).toBe(true)
  })

  it('handles a shift ending exactly at midnight', () => {
    expect(wrapsPastMidnight('22:00', '00:00')).toBe(true)
  })
})
