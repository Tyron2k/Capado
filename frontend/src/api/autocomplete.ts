import type { ApiQuery, ApiResponse } from './contracts'

/**
 * API functions for autocomplete/typeahead search.
 */

import apiClient from './client'
import type { AutocompleteResult } from '../types/resource'

type SearchAutocompleteParams = ApiQuery<'/api/autocomplete', 'get'> & { signal?: AbortSignal }

/**
 * Search for resources for autocomplete suggestions.
 * Supports AbortController via the `signal` parameter for request cancellation.
 */
export async function searchAutocomplete(
  params: SearchAutocompleteParams,
): Promise<AutocompleteResult[]> {
  const { q, type, signal } = params

  const queryParams = { q, type } satisfies ApiQuery<'/api/autocomplete', 'get'>

  const response = await apiClient.get<ApiResponse<'/api/autocomplete', 'get'>>(
    '/api/autocomplete',
    {
      params: queryParams,
      signal,
    },
  )

  return response.data
}
