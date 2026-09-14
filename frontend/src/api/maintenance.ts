/**
 * Read access to the maintenance run log.
 *
 * Exists so the retention numbers in the settings page can be shown next to evidence that
 * pruning actually happened. Before the scheduler, audit retention was set to 24 months on the
 * live instance and nothing had ever deleted a row — a setting nobody could verify.
 */

import apiClient from './client'

export type JobRunStatus = 'running' | 'succeeded' | 'failed' | 'skipped'

/** One maintenance run. Not exported: the panel infers it from getMaintenanceRuns's return type. */
interface JobRun {
  job_name: string
  started_at: string
  finished_at: string | null
  status: JobRunStatus
  /**
   * Rows the job touched.
   *
   * 0 means nothing was old enough yet; null means the job did not get far enough to know.
   * Two different statements, deliberately not collapsed.
   */
  items_affected: number | null
  detail: string
}

export async function getMaintenanceRuns(limit = 20): Promise<JobRun[]> {
  const response = await apiClient.get<JobRun[]>('/api/maintenance/runs', {
    params: { limit },
  })
  return response.data
}
