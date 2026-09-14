/**
 * API functions for the dashboard.
 */

import apiClient from './client'
import type { DashboardResponse } from '../types/dashboard'

/**
 * Fetch dashboard data (aggregated utilization + project list with conflicts).
 * Accepts optional role filter parameters (department, location, project_ids).
 */
export async function getDashboard(params?: Record<string, string>): Promise<DashboardResponse> {
  const response = await apiClient.get<DashboardResponse>('/api/dashboard', {
    params,
  })
  return response.data
}
