import type { ApiQuery, ApiResponse } from './contracts'

/**
 * API functions for resource suggestions.
 */

import apiClient from './client'
import type { ResourceSuggestion } from '../types/suggestion'

/** Fetch resource suggestions based on availability and allocation. */
export async function getSuggestions(
  params: ApiQuery<'/api/suggestions', 'get'>,
): Promise<ResourceSuggestion[]> {
  const response = await apiClient.get<ApiResponse<'/api/suggestions', 'get'>>('/api/suggestions', {
    params,
  })
  return response.data
}
