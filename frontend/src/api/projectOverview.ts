/** HTTP contract and client for the aggregated project overview. */
import apiClient from './client'
import type { components } from './generated/schema'

export type ProjectOverviewItem = components['schemas']['ProjectOverviewItem']
type ProjectOverviewResponse = components['schemas']['ProjectOverviewResponse']

/** Fetch progress, deadlines, capacity and warnings; preserve the response envelope. */
export async function getProjectOverview(projectIds?: string[]): Promise<ProjectOverviewResponse> {
  const params =
    projectIds !== undefined && projectIds.length > 0
      ? { project_ids: projectIds.join(',') }
      : undefined
  const response = await apiClient.get<ProjectOverviewResponse>('/api/projects/overview', {
    params,
  })
  return response.data
}
