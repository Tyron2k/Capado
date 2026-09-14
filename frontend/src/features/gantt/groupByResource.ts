/**
 * Regroup the resource Gantt response by RESOURCE instead of by project.
 *
 * WHY THIS EXISTS: the backend groups by project, which answers "when does project X run". The
 * question people actually bring to this screen is the other one — "what is standing on track 42, and
 * WHEN IS IT FREE". A gap is only visible when a single row belongs to a single resource: with one row
 * per work package spread across project headings, an idle week on track 42 is invisible because its
 * occupancy is scattered over several rows.
 *
 * No backend change is needed. Every bar already carries resource_id and resource_name — the project
 * is merely the heading above it. So this is a pure reshuffle of data already on the client, which is
 * also why it cannot disagree with the project grouping: both views are folds of the same rows.
 *
 * The project name has to be carried DOWN onto each bar during the reshuffle, because it lives on the
 * group being dissolved. Once grouped by resource, the project is the interesting label on the row —
 * the inverse of the project grouping, where the work package name is.
 */

import type { ResourceGanttBar, ResourceGanttResponse } from '../../api/ganttResources'

/** A bar that remembers which project it came from, once the project grouping is dissolved. */
interface ResourceGroupedBar extends ResourceGanttBar {
  project_id: string
  project_name: string
}

interface ResourceGroup {
  resource_id: string
  resource_name: string
  bars: ResourceGroupedBar[]
}

/**
 * Fold the project-grouped response into one group per resource.
 *
 * Resources are sorted by name and their bars chronologically, so reading a row left to right is
 * reading time — without that, a gap between two bars could just be two rows in arbitrary order.
 * Ties break on end_date and then id to keep the order total, matching the backend's list queries.
 */
export function groupByResource(data: ResourceGanttResponse): ResourceGroup[] {
  const byResource = new Map<string, ResourceGroup>()

  for (const project of data.projects) {
    for (const bar of project.work_packages) {
      let group = byResource.get(bar.resource_id)
      if (!group) {
        group = { resource_id: bar.resource_id, resource_name: bar.resource_name, bars: [] }
        byResource.set(bar.resource_id, group)
      }
      group.bars.push({
        ...bar,
        project_id: project.project_id,
        project_name: project.project_name,
      })
    }
  }

  const groups = [...byResource.values()]
  for (const group of groups) {
    group.bars.sort(
      (a, b) =>
        a.start_date.localeCompare(b.start_date) ||
        a.end_date.localeCompare(b.end_date) ||
        a.id.localeCompare(b.id),
    )
  }
  groups.sort((a, b) => a.resource_name.localeCompare(b.resource_name))
  return groups
}
