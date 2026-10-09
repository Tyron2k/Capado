import type { components } from '../api/generated/schema'

/**
 * TypeScript types for resource suggestions.
 * Based on the backend schema in app/schemas/suggestion.py.
 */

export type AvailabilityStatus = ResourceSuggestion['availability_status']

export type ResourceSuggestion = components['schemas']['ResourceSuggestionResponse']
