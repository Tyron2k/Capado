/**
 * Tests for the projects-overview row order.
 *
 * Two properties matter beyond "it sorts": the caller's array must not be mutated — it is React state
 * owned by GanttSection, and sorting it in place would change what the parent holds without a render —
 * and every order must be TOTAL, so two projects sharing a name or a date keep a fixed sequence
 * instead of flipping between renders for no visible reason.
 *
 * All fixtures are inline and fictional.
 */

import { describe, expect, it } from 'vitest'

import { sortProjects } from './sortProjects'
import type { Project } from '../../../types/project'

function project(id: string, name: string, start: string, end: string): Project {
  return {
    id,
    name,
    folder_id: null,
    position: 0,
    external_ref: null,
    start_date: start,
    end_date: end,
    committed_delivery_date: null,
  } as Project
}

const projects = [
  project('c', 'Gamma', '2026-01-10', '2026-12-01'),
  project('a', 'Alpha', '2026-06-01', '2026-06-30'),
  project('b', 'Beta', '2026-03-01', '2027-01-15'),
]

describe('sortProjects', () => {
  it('sorts by name', () => {
    expect(sortProjects(projects, 'name').map((p) => p.name)).toEqual(['Alpha', 'Beta', 'Gamma'])
  })

  it('sorts by start date, which is a different order than by name', () => {
    expect(sortProjects(projects, 'start').map((p) => p.name)).toEqual(['Gamma', 'Beta', 'Alpha'])
  })

  it('sorts by end date, which is a different order again', () => {
    // Gamma ends before Beta despite starting first — the whole reason end date is its own option.
    expect(sortProjects(projects, 'end').map((p) => p.name)).toEqual(['Alpha', 'Gamma', 'Beta'])
  })

  it('does not mutate the array it was given', () => {
    const input = [...projects]
    const before = input.map((p) => p.id)

    sortProjects(input, 'start')

    // The caller's array is React state; sorting in place would change what the parent holds
    // without a render.
    expect(input.map((p) => p.id)).toEqual(before)
  })

  it('breaks ties on name, then id, so the order is total', () => {
    const sameStart = [
      project('z', 'Same', '2026-05-01', '2026-05-10'),
      project('a', 'Same', '2026-05-01', '2026-05-10'),
      project('m', 'Other', '2026-05-01', '2026-05-10'),
    ]

    // Identical dates AND two identical names: without the id tiebreaker the last two could swap
    // between renders, which reads as the chart twitching for no reason.
    expect(sortProjects(sameStart, 'start').map((p) => p.id)).toEqual(['m', 'a', 'z'])
  })

  it('handles an empty list', () => {
    expect(sortProjects([], 'name')).toEqual([])
  })
})
