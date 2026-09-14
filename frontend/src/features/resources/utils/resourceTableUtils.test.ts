import { describe, expect, it } from 'vitest'

import type { ResourceListItem } from '../../../types/resource'
import { flattenResourceList, filterResources, buildGroupedRows } from './resourceTableUtils'

describe('flattenResourceList', () => {
  it('returns empty array for empty input', () => {
    expect(flattenResourceList([])).toEqual([])
  })

  it('maps ResourceListItem fields to FlatResource', () => {
    const items: ResourceListItem[] = [
      {
        id: 'r1',
        name: 'Resource 1',
        group_id: 'g1',
        group_name: 'Department A',
        is_active: true,
        conflict_count: 2,
      },
    ]

    const result = flattenResourceList(items)

    expect(result).toHaveLength(1)
    expect(result[0]).toEqual({
      id: 'r1',
      name: 'Resource 1',
      group_id: 'g1',
      group_name: 'Department A',
      conflict_count: 2,
    })
  })

  it('carries site_name through to the table row', () => {
    // Regression: site_name was declared in FlatResource, documented, and not copied by the
    // mapping, so the site column rendered an em-dash for every row while the API returned the
    // name correctly. TypeScript stayed silent because the field is optional, and the fixtures
    // in this file did not carry a site_name at all — so nothing here could have caught it.
    const items: ResourceListItem[] = [
      {
        id: 'r1',
        name: 'Resource 1',
        group_id: 'g1',
        group_name: 'Department A',
        site_name: 'Hauptwerk',
        is_active: true,
        conflict_count: 0,
      },
    ]

    expect(flattenResourceList(items)[0].site_name).toBe('Hauptwerk')
  })

  it('leaves site_name undefined when the resource is filed at no site', () => {
    const items: ResourceListItem[] = [
      {
        id: 'r1',
        name: 'Resource 1',
        group_id: 'g1',
        group_name: 'Department A',
        is_active: true,
        conflict_count: 0,
      },
    ]

    expect(flattenResourceList(items)[0].site_name).toBeUndefined()
  })

  it('handles multiple items', () => {
    const items: ResourceListItem[] = [
      { id: 'r1', name: 'A', group_id: 'g1', group_name: 'X', is_active: true, conflict_count: 0 },
      { id: 'r2', name: 'B', group_id: 'g2', group_name: 'Y', is_active: true, conflict_count: 3 },
    ]

    const result = flattenResourceList(items)

    expect(result).toHaveLength(2)
    expect(result[0].name).toBe('A')
    expect(result[1].conflict_count).toBe(3)
  })

  it('handles undefined group_name', () => {
    const items: ResourceListItem[] = [
      { id: 'r1', name: 'A', group_id: 'g1', is_active: true, conflict_count: 0 },
    ]

    const result = flattenResourceList(items)

    expect(result[0].group_name).toBeUndefined()
  })
})

describe('filterResources', () => {
  const resources = [
    { id: '1', name: 'Alpha', group_id: 'g1', group_name: 'X', conflict_count: 0 },
    { id: '2', name: 'Beta', group_id: 'g1', group_name: 'X', conflict_count: 0 },
    { id: '3', name: 'Gamma', group_id: 'g2', group_name: 'Y', conflict_count: 0 },
  ]

  it('returns all resources when search is empty', () => {
    expect(filterResources(resources, '')).toEqual(resources)
  })

  it('returns all resources when search is whitespace', () => {
    expect(filterResources(resources, '   ')).toEqual(resources)
  })

  it('filters by name case-insensitively', () => {
    const result = filterResources(resources, 'alpha')
    expect(result).toHaveLength(1)
    expect(result[0].name).toBe('Alpha')
  })

  it('returns empty array when nothing matches', () => {
    expect(filterResources(resources, 'zzz')).toHaveLength(0)
  })

  it('matches partial strings', () => {
    const result = filterResources(resources, 'eta')
    expect(result).toHaveLength(1)
    expect(result[0].name).toBe('Beta')
  })
})

describe('buildGroupedRows', () => {
  const resources = [
    { id: '1', name: 'A', group_name: 'Group B' },
    { id: '2', name: 'B', group_name: 'Group A' },
    { id: '3', name: 'C', group_name: 'Group A' },
  ]

  it('returns empty array for empty input', () => {
    expect(buildGroupedRows([], 4, () => null)).toEqual([])
  })

  it('sorts by group name and inserts headers', () => {
    const rows = buildGroupedRows(resources, 4, (r) => r.id)

    // Should be: header-Group A, '2', '3', header-Group B, '1'
    expect(rows).toHaveLength(5)
  })

  it('handles resources with undefined group_name', () => {
    const items = [{ id: '1', name: 'X', group_name: undefined }]
    const rows = buildGroupedRows(items, 4, (r) => r.id)

    // header for '—' + the resource
    expect(rows).toHaveLength(2)
  })
})
