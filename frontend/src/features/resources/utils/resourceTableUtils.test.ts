import { describe, expect, it } from 'vitest'

import type { ResourceListItem } from '../../../types/resource'
import { flattenResourceList } from './resourceTableUtils'

describe('flattenResourceList', () => {
  it('returns empty array for empty input', () => {
    expect(flattenResourceList([])).toEqual([])
  })

  it('maps ResourceListItem fields to FlatResource', () => {
    const items: ResourceListItem[] = [
      {
        site_id: null,
        site_name: '',
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
      site_name: '',
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
        site_id: null,
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

  it('retains the empty site name when the resource is filed at no site', () => {
    const items: ResourceListItem[] = [
      {
        site_id: null,
        site_name: '',
        id: 'r1',
        name: 'Resource 1',
        group_id: 'g1',
        group_name: 'Department A',
        is_active: true,
        conflict_count: 0,
      },
    ]

    expect(flattenResourceList(items)[0].site_name).toBe('')
  })

  it('handles multiple items', () => {
    const items: ResourceListItem[] = [
      {
        site_id: null,
        site_name: '',
        id: 'r1',
        name: 'A',
        group_id: 'g1',
        group_name: 'X',
        is_active: true,
        conflict_count: 0,
      },
      {
        site_id: null,
        site_name: '',
        id: 'r2',
        name: 'B',
        group_id: 'g2',
        group_name: 'Y',
        is_active: true,
        conflict_count: 3,
      },
    ]

    const result = flattenResourceList(items)

    expect(result).toHaveLength(2)
    expect(result[0].name).toBe('A')
    expect(result[1].conflict_count).toBe(3)
  })

  it('handles the empty group name', () => {
    const items: ResourceListItem[] = [
      {
        group_name: '',
        site_id: null,
        site_name: '',
        id: 'r1',
        name: 'A',
        group_id: 'g1',
        is_active: true,
        conflict_count: 0,
      },
    ]

    const result = flattenResourceList(items)

    expect(result[0].group_name).toBe('')
  })
})
