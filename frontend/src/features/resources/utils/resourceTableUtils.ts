/**
 * Pure utility functions for transforming resource list data into grouped
 * table rows. All functions are side-effect-free and designed for testability.
 */

import type { ResourceListItem } from '../../../types/resource'

/**
 * Flattened resource for table row rendering.
 * Retains only the fields needed for display in the grouped DataTable.
 */
export type FlatResource = Pick<
  ResourceListItem,
  'id' | 'name' | 'group_id' | 'group_name' | 'site_name' | 'conflict_count'
>

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
