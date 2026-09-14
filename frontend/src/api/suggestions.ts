/**
 * API functions for resource suggestions.
 */

import apiClient from './client'
import type { ResourceSuggestion, SuggestionParams } from '../types/suggestion'

/** Fetch resource suggestions based on availability and allocation. */
export async function getSuggestions(params: SuggestionParams): Promise<ResourceSuggestion[]> {
  const response = await apiClient.get<ResourceSuggestion[]>('/api/suggestions', { params })
  return response.data
}
