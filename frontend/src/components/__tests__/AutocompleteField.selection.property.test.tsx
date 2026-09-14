/**
 * Property-Based Test: Selection sets ID and name correctly
 *
 * Feature: ressourcen-hierarchien-und-autocomplete
 * Property 10: Selection sets ID and name correctly
 *
 * For any autocomplete result selected from the dropdown list:
 * - The input field displays the selected name
 * - The stored ID matches the selected entry's ID
 * - The dropdown is closed (isOpen = false)
 */
import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import type { AutocompleteResult } from '../../types/resource'
import { applySelection, type AutocompleteState } from '../autocompleteSelectionLogic'

// --- Generators ---

/** Generates a random AutocompleteResult with non-empty fields */
const autocompleteResultArb: fc.Arbitrary<AutocompleteResult> = fc.record({
  id: fc.uuid(),
  name: fc.string({ minLength: 1, maxLength: 50 }),
  type: fc.constantFrom('personal' as const, 'infrastructure' as const),
  detail: fc.string({ minLength: 1, maxLength: 100 }),
})

/** Generates a list of 1-10 autocomplete results */
const resultsListArb: fc.Arbitrary<AutocompleteResult[]> = fc.array(autocompleteResultArb, {
  minLength: 1,
  maxLength: 10,
})

/** Generates a valid index within a results list */
function indexForList(list: AutocompleteResult[]): fc.Arbitrary<number> {
  return fc.nat({ max: list.length - 1 })
}

/** Generates a state representing an open dropdown with results */
const openDropdownStateArb: fc.Arbitrary<{
  state: AutocompleteState
  results: AutocompleteResult[]
  selectedIndex: number
}> = resultsListArb.chain((results) =>
  indexForList(results).map((selectedIndex) => ({
    state: {
      inputValue: 'search query',
      isOpen: true,
      results,
      focusedIndex: selectedIndex,
      hasSelected: false,
    },
    results,
    selectedIndex,
  })),
)

// --- Property Tests ---

describe('Feature: ressourcen-hierarchien-und-autocomplete, Property 10: Selection sets ID and name correctly', () => {
  it('after selection, input displays the selected name', () => {
    fc.assert(
      fc.property(openDropdownStateArb, ({ state, results, selectedIndex }) => {
        const selectedResult = results[selectedIndex]
        const { newState } = applySelection(state, selectedResult)

        expect(newState.inputValue).toBe(selectedResult.name)
      }),
      { numRuns: 100 },
    )
  })

  it('after selection, onChange is called with correct id and name', () => {
    fc.assert(
      fc.property(openDropdownStateArb, ({ state, results, selectedIndex }) => {
        const selectedResult = results[selectedIndex]
        const { onChangeCall } = applySelection(state, selectedResult)

        expect(onChangeCall.id).toBe(selectedResult.id)
        expect(onChangeCall.name).toBe(selectedResult.name)
      }),
      { numRuns: 100 },
    )
  })

  it('after selection, dropdown is closed', () => {
    fc.assert(
      fc.property(openDropdownStateArb, ({ state, results, selectedIndex }) => {
        const selectedResult = results[selectedIndex]
        const { newState } = applySelection(state, selectedResult)

        expect(newState.isOpen).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('after selection, results are cleared and focusedIndex is reset', () => {
    fc.assert(
      fc.property(openDropdownStateArb, ({ state, results, selectedIndex }) => {
        const selectedResult = results[selectedIndex]
        const { newState } = applySelection(state, selectedResult)

        expect(newState.results).toEqual([])
        expect(newState.focusedIndex).toBe(-1)
        expect(newState.hasSelected).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('selection behavior is consistent regardless of which item is selected from any list', () => {
    fc.assert(
      fc.property(openDropdownStateArb, ({ state, results, selectedIndex }) => {
        const selectedResult = results[selectedIndex]
        const { newState, onChangeCall } = applySelection(state, selectedResult)

        // All three core properties hold simultaneously:
        // 1. Input shows selected name
        expect(newState.inputValue).toBe(selectedResult.name)
        // 2. onChange called with correct id and name
        expect(onChangeCall.id).toBe(selectedResult.id)
        expect(onChangeCall.name).toBe(selectedResult.name)
        // 3. Dropdown is closed
        expect(newState.isOpen).toBe(false)
      }),
      { numRuns: 100 },
    )
  })
})
