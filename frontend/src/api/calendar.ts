import type { ApiBody, ApiQuery, ApiResponse } from './contracts'

import type { components } from './generated/schema'

/**
 * API functions for the working-time configuration: sites, calendar exceptions,
 * week profiles, their bindings, and infrastructure availability windows.
 *
 * Durations cross the wire as integer MINUTES, matching storage. Hours are a
 * display concern and are formatted in the UI, because rounding at the API
 * boundary would lose the half hours real shift patterns use.
 */

import apiClient from './client'

// ---------------------------------------------------------------------------
// Sites
// ---------------------------------------------------------------------------

export type Site = components['schemas']['SiteResponse']

export type SiteInput = components['schemas']['SiteCreate']

export async function listSites(includeInactive = false): Promise<Site[]> {
  const { data } = await apiClient.get<ApiResponse<'/api/sites', 'get'>>('/api/sites', {
    params: { include_inactive: includeInactive },
  })
  return data
}

export async function createSite(input: ApiBody<'/api/sites', 'post'>): Promise<Site> {
  const { data } = await apiClient.post<ApiResponse<'/api/sites', 'post'>>('/api/sites', input)
  return data
}

export async function updateSite(
  id: string,
  input: ApiBody<'/api/sites/{site_id}', 'put'>,
): Promise<Site> {
  const { data } = await apiClient.put<ApiResponse<'/api/sites/{site_id}', 'put'>>(
    `/api/sites/${id}`,
    input,
  )
  return data
}

export async function deactivateSite(id: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/sites/{site_id}', 'delete'>>(`/api/sites/${id}`)
}

// ---------------------------------------------------------------------------
// Calendar exceptions
// ---------------------------------------------------------------------------

/**
 * A dated override of the week profile for one site.
 *
 * `working_minutes` carries all three cases the backend supports, which is why
 * this is not a boolean: 0 is a non-working day (public holiday, company
 * shutdown, bridge day), a value below the profile is a half day (24 and 31
 * December in most German firms), and a value above zero on a day the profile
 * calls free is a designated working Saturday.
 */
export type Holiday = components['schemas']['HolidayResponse']

export async function listHolidays(params: ApiQuery<'/api/holidays', 'get'>): Promise<Holiday[]> {
  const { data } = await apiClient.get<ApiResponse<'/api/holidays', 'get'>>('/api/holidays', {
    params,
  })
  return data
}

export async function createHoliday(input: ApiBody<'/api/holidays', 'post'>): Promise<Holiday> {
  const { data } = await apiClient.post<ApiResponse<'/api/holidays', 'post'>>(
    '/api/holidays',
    input,
  )
  return data
}

export async function updateHoliday(
  id: string,
  input: ApiBody<'/api/holidays/{holiday_id}', 'put'>,
): Promise<Holiday> {
  const { data } = await apiClient.put<ApiResponse<'/api/holidays/{holiday_id}', 'put'>>(
    `/api/holidays/${id}`,
    input,
  )
  return data
}

export async function deleteHoliday(id: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/holidays/{holiday_id}', 'delete'>>(`/api/holidays/${id}`)
}

// ---------------------------------------------------------------------------
// Week profiles
// ---------------------------------------------------------------------------

export type WorkWeekProfile = components['schemas']['WorkWeekProfileResponse']

export async function listWorkWeekProfiles(): Promise<WorkWeekProfile[]> {
  const { data } =
    await apiClient.get<ApiResponse<'/api/work-week-profiles', 'get'>>('/api/work-week-profiles')
  return data
}

export async function createWorkWeekProfile(
  input: ApiBody<'/api/work-week-profiles', 'post'>,
): Promise<WorkWeekProfile> {
  const { data } = await apiClient.post<ApiResponse<'/api/work-week-profiles', 'post'>>(
    '/api/work-week-profiles',
    input,
  )
  return data
}

export async function updateWorkWeekProfile(
  id: string,
  input: ApiBody<'/api/work-week-profiles/{profile_id}', 'put'>,
): Promise<WorkWeekProfile> {
  const { data } = await apiClient.put<ApiResponse<'/api/work-week-profiles/{profile_id}', 'put'>>(
    `/api/work-week-profiles/${id}`,
    input,
  )
  return data
}

export async function deleteWorkWeekProfile(id: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/work-week-profiles/{profile_id}', 'delete'>>(
    `/api/work-week-profiles/${id}`,
  )
}

// ---------------------------------------------------------------------------
// Profile bindings
// ---------------------------------------------------------------------------

/**
 * Binds a week profile to a resource OR a resource group — exactly one.
 *
 * The group binding is the normal case: a department states its hours once. An
 * individual binding overrides it, which is how the one part-time employee is
 * handled without giving all 1600 people a row of their own.
 */
export type ResourceWorkProfileBinding = components['schemas']['ResourceWorkProfileResponse']

export async function listBindings(
  params: ApiQuery<'/api/resource-work-profiles', 'get'>,
): Promise<ResourceWorkProfileBinding[]> {
  const { data } = await apiClient.get<ApiResponse<'/api/resource-work-profiles', 'get'>>(
    '/api/resource-work-profiles',
    { params },
  )
  return data
}

export async function createBinding(
  input: ApiBody<'/api/resource-work-profiles', 'post'>,
): Promise<ResourceWorkProfileBinding> {
  const { data } = await apiClient.post<ApiResponse<'/api/resource-work-profiles', 'post'>>(
    '/api/resource-work-profiles',
    input,
  )
  return data
}

export async function deleteBinding(id: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/resource-work-profiles/{binding_id}', 'delete'>>(
    `/api/resource-work-profiles/${id}`,
  )
}

// ---------------------------------------------------------------------------
// Infrastructure availability windows
// ---------------------------------------------------------------------------

/**
 * A clock window on one weekday during which a resource may be booked.
 *
 * `weekday` is the day the window STARTS on. An `end_time` before `start_time`
 * means the window runs past midnight, so a night shift 22:00–06:00 is one row
 * rather than two. Equal times are rejected by the backend.
 *
 * A resource with no windows at all is available around the clock.
 */
export type AvailabilityWindow = components['schemas']['AvailabilityWindowResponse']

export async function listAvailabilityWindows(resourceId: string): Promise<AvailabilityWindow[]> {
  const { data } = await apiClient.get<
    ApiResponse<'/api/infrastructure/{resource_id}/windows', 'get'>
  >(`/api/infrastructure/${resourceId}/windows`)
  return data
}

export async function createAvailabilityWindow(
  input: ApiBody<'/api/infrastructure-windows', 'post'>,
): Promise<AvailabilityWindow> {
  const { data } = await apiClient.post<ApiResponse<'/api/infrastructure-windows', 'post'>>(
    '/api/infrastructure-windows',
    input,
  )
  return data
}

export async function deleteAvailabilityWindow(id: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/infrastructure-windows/{window_id}', 'delete'>>(
    `/api/infrastructure-windows/${id}`,
  )
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

/**
 * Format minutes as hours for display, e.g. 480 -> "8:00", 450 -> "7:30".
 *
 * Half hours are preserved because shift patterns use them; rounding to whole
 * hours here would misreport a 7.5-hour day as 8.
 */
export function formatMinutes(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return `${hours}:${String(rest).padStart(2, '0')}`
}

/** Parse an "H:MM" or "H" string into minutes, or null when unparseable. */
export function parseMinutes(value: string): number | null {
  const trimmed = value.trim()
  if (trimmed === '') return null
  const match = /^(\d{1,2})(?::([0-5]\d))?$/.exec(trimmed)
  if (!match) return null
  const hours = Number(match[1])
  const rest = match[2] ? Number(match[2]) : 0
  const total = hours * 60 + rest
  return total > 1440 ? null : total
}

/**
 * Whether a window runs past midnight.
 *
 * A window whose end is not after its start wraps into the next day. Callers use
 * this to label such a row rather than showing an interval that reads backwards.
 */
export function wrapsPastMidnight(startTime: string, endTime: string): boolean {
  return endTime <= startTime
}
