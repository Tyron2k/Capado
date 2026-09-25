import { describe, expect, it } from 'vitest'
import type { Assignment } from '../../types/assignment'
import type { ConflictSuggestion } from '../../api/assignments'
import { patchForSuggestion, previewPayloadForPatch } from './suggestionChange'

const personal = {
  id: 'a1',
  resource_id: 'r1',
  resource_type: 'personal',
  work_package_id: 'w1',
  start_date: '2026-03-28',
  end_date: '2026-04-02',
  allocation_percent: 80,
  start_at: null,
  end_at: null,
} as Assignment

const infrastructure = {
  ...personal,
  resource_type: 'infrastructure',
  start_date: null,
  end_date: null,
  allocation_percent: null,
  start_at: '2026-03-28T22:00:00',
  end_at: '2026-03-29T02:00:00',
} as Assignment

function suggestion(type: ConflictSuggestion['type'], extras: Partial<ConflictSuggestion>) {
  return { type, assignment_id: 'a1', description: 'test', ...extras }
}

describe('conflict suggestion preview and apply payloads', () => {
  it('shifts calendar dates over DST without changing the assignment duration', () => {
    const patch = patchForSuggestion(suggestion('shift_forward', { shift_days: 2 }), personal)
    expect(patch).toEqual({ start_date: '2026-03-30', end_date: '2026-04-04' })
    expect(previewPayloadForPatch(personal, patch)).toMatchObject({
      assignment_id: 'a1',
      resource_id: 'r1',
      start_date: '2026-03-30',
      end_date: '2026-04-04',
      allocation_percent: 80,
    })
  })

  it('preserves local clock time on an infrastructure day shift', () => {
    expect(
      patchForSuggestion(suggestion('shift_backward', { shift_days: -2 }), infrastructure),
    ).toEqual({
      start_at: '2026-03-26T22:00:00',
      end_at: '2026-03-27T02:00:00',
    })
  })

  it('moves a booking into an operating window while preserving its elapsed duration', () => {
    const patch = patchForSuggestion(
      suggestion('shift_into_window', { new_start_at: '2026-03-29T08:00:00' }),
      infrastructure,
    )
    expect(patch).toEqual({
      start_at: '2026-03-29T08:00:00',
      end_at: '2026-03-29T12:00:00.000',
    })
  })

  it('previews both sides of a resource swap using the same patch sent by Apply', () => {
    const patch = patchForSuggestion(
      suggestion('swap_resource', { target_resource_id: 'r2' }),
      personal,
    )
    expect(patch).toEqual({ resource_id: 'r2' })
    expect(previewPayloadForPatch(personal, patch)).toMatchObject({
      assignment_id: 'a1',
      resource_id: 'r2',
      start_date: personal.start_date,
      end_date: personal.end_date,
    })
  })
})
