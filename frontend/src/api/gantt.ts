/**
 * API functions for Gantt data.
 */

import apiClient from './client'

interface GanttResourceInfo {
  id: string
  name: string
  resource_type: 'personal' | 'infrastructure'
}

interface GanttResourceAssignment {
  id: string
  name: string
  resource_type: 'personal' | 'infrastructure'
  allocation_percent: number
}

export interface GanttWorkPackageBar {
  id: string
  name: string
  start_date: string // ISO date string (YYYY-MM-DD)
  end_date: string // ISO date string (YYYY-MM-DD)
  resources: GanttResourceInfo[]
  resource_assignments: GanttResourceAssignment[]
  has_conflict: boolean
}

interface GanttResponse {
  project_id: string
  project_name: string
  work_packages: GanttWorkPackageBar[]
}

/** Fetch Gantt data for a project. */
export async function getGanttData(projectId: string): Promise<GanttResponse> {
  const response = await apiClient.get<GanttResponse>(`/api/gantt/projects/${projectId}`)
  return response.data
}
