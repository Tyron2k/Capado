/**
 * Pure utility functions for transforming resource list data into grouped
 * table rows. All functions are side-effect-free and designed for testability.
 */

import type { ReactNode } from 'react'

import type { ResourceListItem } from '../../../types/resource'
import { GroupHeaderRow } from '../components/GroupHeaderRow'

/**
 * Flattened resource for table row rendering.
 * Retains only the fields needed for display in the grouped DataTable.
 */
export interface FlatResource {
  id: string
  name: string
  group_id: string
  group_name?: string
  /** Name of the site, or empty when the resource is filed at none. */
  site_name?: string
  conflict_count: number
}

/**
 * Converts a resource list (from the tree/list endpoint) into a flat array
 * suitable for table rendering.
 *
 * Copy EVERY field the table renders. `site_name` was declared in FlatResource,
 * documented with a comment, and not copied here — so the site column rendered an
 * em-dash for every row while the API returned the name correctly. TypeScript stayed
 * silent because the field is optional, and no test looked at it. Found by taking a
 * screenshot, which is the only place the empty column was visible.
 */
export function flattenResourceList(items: ResourceListItem[]): FlatResource[] {
  return items.map((item) => ({
    id: item.id,
    name: item.name,
    group_id: item.group_id,
    group_name: item.group_name,
    site_name: item.site_name,
    conflict_count: item.conflict_count,
  }))
}

/**
 * Groups resources by their `group_name` and produces an array of React elements
 * containing GroupHeaderRow separators followed by resource data rows.
 *
 * Resources are sorted by group name using locale-aware comparison (`'de'`).
 * A GroupHeaderRow is inserted before each group's resources displaying the
 * group name and resource count.
 *
 * @param resources - Flat array of resources (already filtered by search).
 * @param colSpan - Number of columns for the header row to span.
 * @param renderRow - Function to render a single resource data row.
 * @returns Array of ReactNode elements (headers + data rows).
 */
export function buildGroupedRows<T extends { group_name?: string; id: string }>(
  resources: T[],
  colSpan: number,
  renderRow: (resource: T) => ReactNode,
): ReactNode[] {
  // Sort by group name (alphabetical, locale-aware German)
  const sorted = [...resources].sort((a, b) =>
    (a.group_name ?? '').localeCompare(b.group_name ?? '', 'de'),
  )

  const rows: ReactNode[] = []
  let currentGroup: string | null = null

  for (const resource of sorted) {
    const group = resource.group_name ?? '—'
    if (group !== currentGroup) {
      const groupCount = sorted.filter((r) => (r.group_name ?? '—') === group).length
      rows.push(
        GroupHeaderRow({
          groupName: group,
          count: groupCount,
          colSpan,
        }),
      )
      currentGroup = group
    }
    rows.push(renderRow(resource))
  }

  return rows
}

/**
 * Filters resources by name using case-insensitive matching.
 * Returns all resources if the search string is empty or whitespace-only.
 *
 * @param resources - Array of resources to filter.
 * @param search - The search string to match against resource names.
 * @returns Filtered array of resources whose names contain the search string.
 */
export function filterResources<T extends { name: string }>(resources: T[], search: string): T[] {
  if (!search.trim()) return resources
  const needle = search.toLowerCase()
  return resources.filter((r) => r.name.toLowerCase().includes(needle))
}
