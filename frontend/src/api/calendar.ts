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

export interface Site {
  id: string
  name: string
  region_code: string | null
  is_default: boolean
  is_active: boolean
}

export interface SiteInput {
  name: string
  region_code?: string | null
  is_default?: boolean
}

export async function listSites(includeInactive = false): Promise<Site[]> {
  const { data } = await apiClient.get<Site[]>('/api/sites', {
    params: { include_inactive: includeInactive },
  })
  return data
}

export async function createSite(input: SiteInput): Promise<Site> {
  const { data } = await apiClient.post<Site>('/api/sites', input)
  return data
}

export async function updateSite(
  id: string,
  input: Partial<SiteInput> & { is_active?: boolean },
): Promise<Site> {
  const { data } = await apiClient.put<Site>(`/api/sites/${id}`, input)
  return data
}

export async function deactivateSite(id: string): Promise<void> {
  await apiClient.delete(`/api/sites/${id}`)
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
export interface Holiday {
  id: string
  site_id: string
  day: string
  name: string
  working_minutes: number
}

interface HolidayInput {
  site_id: string
  day: string
  name: string
  working_minutes?: number
}

export async function listHolidays(params: {
  site_id?: string
  from?: string
  to?: string
}): Promise<Holiday[]> {
  const { data } = await apiClient.get<Holiday[]>('/api/holidays', { params })
  return data
}

export async function createHoliday(input: HolidayInput): Promise<Holiday> {
  const { data } = await apiClient.post<Holiday>('/api/holidays', input)
  return data
}

export async function updateHoliday(
  id: string,
  input: { name?: string; working_minutes?: number },
): Promise<Holiday> {
  const { data } = await apiClient.put<Holiday>(`/api/holidays/${id}`, input)
  return data
}

export async function deleteHoliday(id: string): Promise<void> {
  await apiClient.delete(`/api/holidays/${id}`)
}

// ---------------------------------------------------------------------------
// Week profiles
// ---------------------------------------------------------------------------

export interface WorkWeekProfile {
  id: string
  name: string
  description: string | null
  monday_minutes: number
  tuesday_minutes: number
  wednesday_minutes: number
  thursday_minutes: number
  friday_minutes: number
  saturday_minutes: number
  sunday_minutes: number
  is_default: boolean
  weekly_minutes: number
}

type WorkWeekProfileInput = Omit<WorkWeekProfile, 'id' | 'weekly_minutes'>

export async function listWorkWeekProfiles(): Promise<WorkWeekProfile[]> {
  const { data } = await apiClient.get<WorkWeekProfile[]>('/api/work-week-profiles')
  return data
}

export async function createWorkWeekProfile(
  input: Partial<WorkWeekProfileInput> & { name: string },
): Promise<WorkWeekProfile> {
  const { data } = await apiClient.post<WorkWeekProfile>('/api/work-week-profiles', input)
  return data
}

export async function updateWorkWeekProfile(
  id: string,
  input: Partial<WorkWeekProfileInput>,
): Promise<WorkWeekProfile> {
  const { data } = await apiClient.put<WorkWeekProfile>(`/api/work-week-profiles/${id}`, input)
  return data
}

export async function deleteWorkWeekProfile(id: string): Promise<void> {
  await apiClient.delete(`/api/work-week-profiles/${id}`)
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
export interface ResourceWorkProfileBinding {
  id: string
  resource_id: string | null
  group_id: string | null
  profile_id: string
  valid_from: string
  valid_until: string | null
}

interface BindingInput {
  profile_id: string
  valid_from: string
  valid_until?: string | null
  resource_id?: string | null
  group_id?: string | null
}

export async function listBindings(params: {
  resource_id?: string
  group_id?: string
}): Promise<ResourceWorkProfileBinding[]> {
  const { data } = await apiClient.get<ResourceWorkProfileBinding[]>(
    '/api/resource-work-profiles',
    { params },
  )
  return data
}

export async function createBinding(input: BindingInput): Promise<ResourceWorkProfileBinding> {
  const { data } = await apiClient.post<ResourceWorkProfileBinding>(
    '/api/resource-work-profiles',
    input,
  )
  return data
}

export async function deleteBinding(id: string): Promise<void> {
  await apiClient.delete(`/api/resource-work-profiles/${id}`)
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
export interface AvailabilityWindow {
  id: string
  resource_id: string
  weekday: number
  start_time: string
  end_time: string
}

interface AvailabilityWindowInput {
  resource_id: string
  weekday: number
  start_time: string
  end_time: string
}

export async function listAvailabilityWindows(resourceId: string): Promise<AvailabilityWindow[]> {
  const { data } = await apiClient.get<AvailabilityWindow[]>(
    `/api/infrastructure/${resourceId}/windows`,
  )
  return data
}

export async function createAvailabilityWindow(
  input: AvailabilityWindowInput,
): Promise<AvailabilityWindow> {
  const { data } = await apiClient.post<AvailabilityWindow>('/api/infrastructure-windows', input)
  return data
}

export async function deleteAvailabilityWindow(id: string): Promise<void> {
  await apiClient.delete(`/api/infrastructure-windows/${id}`)
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
