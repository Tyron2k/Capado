import type { ApiResponse } from './contracts'

import type { components } from './generated/schema'

/**
 * API functions for Gantt data.
 */

import apiClient from './client'

export type GanttWorkPackageBar = components['schemas']['GanttWorkPackageBar']

type GanttResponse = components['schemas']['GanttResponse']

/** Fetch Gantt data for a project. */
export async function getGanttData(projectId: string): Promise<GanttResponse> {
  const response = await apiClient.get<ApiResponse<'/api/gantt/projects/{project_id}', 'get'>>(
    `/api/gantt/projects/${projectId}`,
  )
  return response.data
}
