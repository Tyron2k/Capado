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
  start_at: '2026-03-28T21:00:00Z', // 22:00 in Berlin
  end_at: '2026-03-29T02:00:00Z', // 04:00 after the DST jump
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

  it('uses the exact server interval for infrastructure day shifts', () => {
    expect(
      patchForSuggestion(
        suggestion('shift_backward', {
          shift_days: -2,
          new_start_at: '2026-03-26T21:00:00.000Z',
          new_end_at: '2026-03-27T03:00:00.000Z',
        }),
        infrastructure,
      ),
    ).toEqual({
      start_at: '2026-03-26T21:00:00.000Z',
      end_at: '2026-03-27T03:00:00.000Z',
    })
  })

  it('moves a booking into an operating window while preserving its elapsed duration', () => {
    const patch = patchForSuggestion(
      suggestion('shift_into_window', {
        new_start_at: '2026-03-29T06:00:00Z',
        new_end_at: '2026-03-29T11:00:00.000Z',
      }),
      infrastructure,
    )
    expect(patch).toEqual({
      start_at: '2026-03-29T06:00:00Z',
      end_at: '2026-03-29T11:00:00.000Z',
    })
  })

  it('never falls back to client-side calendar arithmetic for incomplete infrastructure suggestions', () => {
    expect(() =>
      patchForSuggestion(suggestion('shift_forward', { shift_days: 1 }), infrastructure),
    ).toThrow()
    expect(() =>
      patchForSuggestion(
        suggestion('shift_into_window', {
          new_start_at: '2026-03-29T06:00:00Z',
          new_end_at: '2026-03-29T05:00:00Z',
        }),
        infrastructure,
      ),
    ).toThrow()
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
