import type { components } from '../api/generated/schema'

/**
 * TypeScript types for the dashboard.
 * Based on the backend schemas in app/schemas/dashboard.py.
 */

/** Color indicator for utilization level (green = ok, yellow = warn, red = overloaded). */

export type WeeklyUtilizationResponse =
  components['schemas']['app__schemas__dashboard__WeeklyUtilizationResponse']

export type DashboardResponse = components['schemas']['DashboardResponse']
