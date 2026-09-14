/**
 * One team's week as a grid, for printing and posting.
 *
 * Addressed to whoever runs the team, not to individuals: per-person logins were struck from
 * this project deliberately, and a sheet for a group is the replacement rather than a stopgap.
 */

import apiClient from './client'

export interface DayEntry {
  work_package_name: string
  project_name: string
  allocation_percent: number
}

export interface DayCell {
  day: string
  entries: DayEntry[]
  absence_percent: number
  /** How much of the absence is still only requested — the part a foreman could renegotiate. */
  provisional_percent: number
  /**
   * False for a weekend or works holiday.
   *
   * Sent explicitly because a blank cell would otherwise be indistinguishable from "nothing
   * planned", and a closed plant is a different message from an empty Tuesday.
   */
  is_working_day: boolean
  is_overbooked: boolean
}

export interface PersonRow {
  resource_id: string
  name: string
  cells: DayCell[]
  /** False for somebody with nothing planned all week — kept, not dropped. */
  has_anything: boolean
}

export interface TeamWeek {
  group_id: string
  group_name: string
  days: string[]
  rows: PersonRow[]
}

/**
 * @param weekOf Any date in the wanted week (YYYY-MM-DD). Omit for the current one. A Sunday
 *   looks BACK to Monday, so opening the sheet on Sunday shows the week that is ending.
 */
export async function getTeamWeek(groupId: string, weekOf?: string): Promise<TeamWeek> {
  const response = await apiClient.get<TeamWeek>(`/api/team-week/${groupId}`, {
    params: weekOf ? { week_of: weekOf } : undefined,
  })
  return response.data
}
