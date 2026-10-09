import type { ApiResponse } from './contracts'

import type { components } from './generated/schema'

/**
 * One team's week as a grid, for printing and posting.
 *
 * Addressed to whoever runs the team, not to individuals: per-person logins were struck from
 * this project deliberately, and a sheet for a group is the replacement rather than a stopgap.
 */

import apiClient from './client'

export type DayCell = components['schemas']['DayCellResponse']

export type TeamWeek = components['schemas']['TeamWeekResponse']

/**
 * @param weekOf Any date in the wanted week (YYYY-MM-DD). Omit for the current one. A Sunday
 *   looks BACK to Monday, so opening the sheet on Sunday shows the week that is ending.
 */
export async function getTeamWeek(groupId: string, weekOf?: string): Promise<TeamWeek> {
  const response = await apiClient.get<ApiResponse<'/api/team-week/{group_id}', 'get'>>(
    `/api/team-week/${groupId}`,
    {
      params: weekOf ? { week_of: weekOf } : undefined,
    },
  )
  return response.data
}
