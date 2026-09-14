/**
 * API functions for autocomplete/typeahead search.
 */

import apiClient from './client'
import type { AutocompleteResult } from '../types/resource'

interface SearchAutocompleteParams {
  q: string
  type: 'personal' | 'infrastructure'
  signal?: AbortSignal
}

/**
 * Search for resources for autocomplete suggestions.
 * Supports AbortController via the `signal` parameter for request cancellation.
 */
export async function searchAutocomplete(
  params: SearchAutocompleteParams,
): Promise<AutocompleteResult[]> {
  const { q, type, signal } = params

  const queryParams: Record<string, string> = { q, type }

  const response = await apiClient.get<AutocompleteResult[]>('/api/autocomplete', {
    params: queryParams,
    signal,
  })

  return response.data
}
