import type { ApiResponse } from './contracts'

import type { components } from './generated/schema'

/**
 * Read access to the maintenance run log.
 *
 * Exists so the retention numbers in the settings page can be shown next to evidence that
 * pruning actually happened. Before the scheduler, audit retention was set to 24 months on the
 * live instance and nothing had ever deleted a row — a setting nobody could verify.
 */

import apiClient from './client'

export type JobRunStatus = JobRun['status']

/** One maintenance run. Not exported: the panel infers it from getMaintenanceRuns's return type. */
type JobRun = components['schemas']['JobRunResponse']

export async function getMaintenanceRuns(limit = 20): Promise<JobRun[]> {
  const response = await apiClient.get<ApiResponse<'/api/maintenance/runs', 'get'>>(
    '/api/maintenance/runs',
    {
      params: { limit },
    },
  )
  return response.data
}
