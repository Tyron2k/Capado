import type { ApiResponse } from './contracts'

import type { components } from './generated/schema'

/**
 * API functions for Gantt resource data.
 */

import apiClient from './client'

export type ResourceGanttBar = components['schemas']['ResourceGanttBarSchema']

export type ResourceGanttResponse = components['schemas']['ResourceGanttResponseSchema']

/** Fetch Gantt data for an infrastructure group. */
export async function getInfraGroupGanttData(groupId: string): Promise<ResourceGanttResponse> {
  const response = await apiClient.get<
    ApiResponse<'/api/gantt/resources/infrastructure/{group_id}', 'get'>
  >(`/api/gantt/resources/infrastructure/${groupId}`)
  return response.data
}

/** Fetch Gantt data for a department. */
export async function getDepartmentGanttData(
  departmentName: string,
): Promise<ResourceGanttResponse> {
  const response = await apiClient.get<
    ApiResponse<'/api/gantt/resources/department/{department_name}', 'get'>
  >(`/api/gantt/resources/department/${encodeURIComponent(departmentName)}`)
  return response.data
}
