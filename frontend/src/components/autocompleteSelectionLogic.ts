/**
 * Pure state transition logic for AutocompleteField selection behavior.
 * Extracted for testability (property-based testing without DOM).
 */
import type { AutocompleteResult } from '../types/resource'

export interface AutocompleteState {
  inputValue: string
  isOpen: boolean
  results: AutocompleteResult[]
  focusedIndex: number
  hasSelected: boolean
}

interface SelectionEffect {
  newState: AutocompleteState
  onChangeCall: { id: string; name: string }
}

/**
 * Computes the new state and side effects after selecting an autocomplete result.
 * This mirrors the handleSelect logic in AutocompleteField.tsx.
 */
export function applySelection(
  _currentState: AutocompleteState,
  selectedResult: AutocompleteResult,
): SelectionEffect {
  return {
    newState: {
      inputValue: selectedResult.name,
      isOpen: false,
      results: [],
      focusedIndex: -1,
      hasSelected: true,
    },
    onChangeCall: {
      id: selectedResult.id,
      name: selectedResult.name,
    },
  }
}
