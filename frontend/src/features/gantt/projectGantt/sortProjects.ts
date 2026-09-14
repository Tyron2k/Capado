/**
 * Row order for the projects overview.
 *
 * WHY NOT THE BACKEND ORDER: the projects endpoint sorts by `position, name`, and `position` is the
 * manual sequence WITHIN A FOLDER — units of one order are worked through in that sequence. Listing
 * every project across all folders on one axis makes that ordering meaningless rather than helpful:
 * position 1 of folder A interleaves with position 1 of folder B, so the result reads as arbitrary.
 * Hence an explicit choice here, defaulting to name.
 *
 * Every comparison ends in a tiebreaker that cannot repeat, for the same reason the backend's list
 * queries do: two projects may share a name, or a start date, and without a total order their relative
 * position would flip between renders for no visible reason.
 */

import type { Project } from '../../../types/project'

export type ProjectSortKey = 'name' | 'start' | 'end'

/** Sort a copy — never the caller's array, which is React state owned elsewhere. */
export function sortProjects(projects: Project[], key: ProjectSortKey): Project[] {
  const byName = (a: Project, b: Project) =>
    a.name.localeCompare(b.name) || a.id.localeCompare(b.id)

  return [...projects].sort((a, b) => {
    switch (key) {
      case 'start':
        // ISO dates compare correctly as strings, which avoids constructing a Date per comparison.
        return a.start_date.localeCompare(b.start_date) || byName(a, b)
      case 'end':
        return a.end_date.localeCompare(b.end_date) || byName(a, b)
      default:
        return byName(a, b)
    }
  })
}
