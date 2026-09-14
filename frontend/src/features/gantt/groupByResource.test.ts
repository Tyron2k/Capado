/**
 * Tests for the by-resource fold of the Gantt response.
 *
 * The point of the view is spotting a GAP — "track 42 is free in week 12". That only works if one row
 * holds everything standing on one resource, in time order. So the invariants worth pinning are: no
 * bar is lost or invented, every bar lands under its own resource, each row reads left to right as
 * time, and the project name survives the fold (it lives on the group being dissolved, so it is the
 * one thing that could silently go missing).
 *
 * All fixtures are inline and fictional.
 */

import { describe, expect, it } from 'vitest'

import { groupByResource } from './groupByResource'
import type { ResourceGanttResponse } from '../../api/ganttResources'

function bar(
  id: string,
  resourceId: string,
  resourceName: string,
  start: string,
  end: string,
  hasConflict = false,
) {
  return {
    id,
    name: `Work package ${id}`,
    start_date: start,
    end_date: end,
    resource_id: resourceId,
    resource_name: resourceName,
    allocation_percent: 100,
    has_conflict: hasConflict,
  }
}

/**
 * Two projects sharing two tracks, deliberately interleaved: project Beta comes first in the
 * response and occupies track 42 EARLIER than project Alpha does, so a fold that merely concatenated
 * in response order would produce a row that runs backwards in time.
 */
const response: ResourceGanttResponse = {
  resource_type: 'infrastructure',
  resource_name: 'Tracks',
  projects: [
    {
      project_id: 'p-beta',
      project_name: 'Beta',
      work_packages: [
        bar('b1', 'r-42', 'Track 42', '2026-03-01', '2026-03-10'),
        bar('b2', 'r-07', 'Track 07', '2026-05-01', '2026-05-10'),
      ],
    },
    {
      project_id: 'p-alpha',
      project_name: 'Alpha',
      work_packages: [
        bar('a1', 'r-42', 'Track 42', '2026-06-01', '2026-06-10', true),
        bar('a2', 'r-42', 'Track 42', '2026-01-05', '2026-01-20'),
      ],
    },
  ],
}

describe('groupByResource', () => {
  it('produces one group per resource, not per work package', () => {
    const groups = groupByResource(response)

    expect(groups.map((g) => g.resource_name)).toEqual(['Track 07', 'Track 42'])
  })

  it('loses no bar and invents none', () => {
    const groups = groupByResource(response)

    const ids = groups.flatMap((g) => g.bars.map((b) => b.id)).sort()
    expect(ids).toEqual(['a1', 'a2', 'b1', 'b2'])
  })

  it('puts every bar under its own resource', () => {
    const groups = groupByResource(response)

    for (const group of groups) {
      for (const b of group.bars) {
        expect(b.resource_id).toBe(group.resource_id)
      }
    }
  })

  it('orders each row chronologically, across project boundaries', () => {
    const groups = groupByResource(response)
    const track42 = groups.find((g) => g.resource_id === 'r-42')!

    // Response order was b1, a1, a2 — grouped by project. Read as time it must be a2, b1, a1.
    // Without this a "gap" between two bars would just be two rows in arbitrary order.
    expect(track42.bars.map((b) => b.id)).toEqual(['a2', 'b1', 'a1'])
  })

  it('carries the project name down onto each bar', () => {
    const groups = groupByResource(response)
    const track42 = groups.find((g) => g.resource_id === 'r-42')!

    // The project lives on the group being dissolved, so it is the one field that could vanish
    // silently — and once grouped by resource it is exactly what the row label shows.
    expect(track42.bars.map((b) => b.project_name)).toEqual(['Alpha', 'Beta', 'Alpha'])
  })

  it('keeps the conflict flag intact', () => {
    const groups = groupByResource(response)
    const track42 = groups.find((g) => g.resource_id === 'r-42')!

    // Red means conflict, and that survives the fold — it is the reason the bars were not given
    // per-work-package colours in the first place.
    expect(track42.bars.find((b) => b.id === 'a1')?.has_conflict).toBe(true)
    expect(track42.bars.find((b) => b.id === 'b1')?.has_conflict).toBe(false)
  })

  it('returns nothing for a response with no bars rather than throwing', () => {
    expect(
      groupByResource({
        resource_type: 'infrastructure',
        resource_name: 'Empty',
        projects: [{ project_id: 'p', project_name: 'P', work_packages: [] }],
      }),
    ).toEqual([])
  })
})
