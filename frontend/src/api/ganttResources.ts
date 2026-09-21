/**
 * API functions for Gantt resource data.
 */

import apiClient from './client'

export interface ResourceGanttBar {
  id: string
  name: string
  start_date: string // ISO date string (YYYY-MM-DD)
  end_date: string // ISO date string (YYYY-MM-DD)
  resource_id: string
  resource_name: string
  allocation_percent: number
  has_conflict: boolean
}

interface ResourceGanttProjectGroup {
  project_id: string
  project_name: string
  work_packages: ResourceGanttBar[]
}

export interface ResourceGanttResponse {
  resource_type: 'infrastructure' | 'department'
  resource_name: string
  projects: ResourceGanttProjectGroup[]
}

/** Fetch Gantt data for an infrastructure group. */
export async function getInfraGroupGanttData(groupId: string): Promise<ResourceGanttResponse> {
  const response = await apiClient.get<ResourceGanttResponse>(
    `/api/gantt/resources/infrastructure/${groupId}`,
  )
  return response.data
}

/** Fetch Gantt data for a department. */
export async function getDepartmentGanttData(
  departmentName: string,
): Promise<ResourceGanttResponse> {
  const response = await apiClient.get<ResourceGanttResponse>(
    `/api/gantt/resources/department/${encodeURIComponent(departmentName)}`,
  )
  return response.data
}
