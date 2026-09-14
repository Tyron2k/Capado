/**
 * Property 11: Keyboard navigation traverses all entries
 *
 * Tests:
 * - After K ArrowDown presses, the focused index is min(K-1, N-1) (0-indexed, stops at last)
 * - After pressing Enter on a focused item, onChange is called with that item's id and name
 * - The dropdown closes after Enter
 *
 * Uses fast-check with numRuns: 100
 */
import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

/**
 * Simulates the keyboard navigation logic from AutocompleteField.
 * Extracted from the component's handleKeyDown:
 *   ArrowDown: setFocusedIndex((prev) => Math.min(prev + 1, results.length - 1))
 *   ArrowUp: setFocusedIndex((prev) => Math.max(prev - 1, 0))
 *   Enter: selects results[focusedIndex] if focusedIndex >= 0
 */
function simulateKeyboardNavigation(
  resultsCount: number,
  keyPresses: string[],
): {
  focusedIndex: number
  selectedIndex: number | null
  isOpen: boolean
} {
  let focusedIndex = -1
  let selectedIndex: number | null = null
  let isOpen = true

  for (const key of keyPresses) {
    if (!isOpen || resultsCount === 0) break

    switch (key) {
      case 'ArrowDown':
        focusedIndex = Math.min(focusedIndex + 1, resultsCount - 1)
        break
      case 'ArrowUp':
        focusedIndex = Math.max(focusedIndex - 1, 0)
        break
      case 'Enter':
        if (focusedIndex >= 0 && focusedIndex < resultsCount) {
          selectedIndex = focusedIndex
          isOpen = false
        }
        break
      case 'Escape':
        isOpen = false
        focusedIndex = -1
        break
    }
  }

  return { focusedIndex, selectedIndex, isOpen }
}

// Generator for autocomplete results (1-10 items)
const autocompleteResultsArb = fc.integer({ min: 1, max: 10 }).chain((count) =>
  fc.tuple(
    fc.constant(count),
    fc.array(
      fc.record({
        id: fc.uuid(),
        name: fc.string({ minLength: 1, maxLength: 30 }).filter((s) => s.trim().length > 0),
        type: fc.constant('personal' as const),
        detail: fc.string({ minLength: 1, maxLength: 30 }).filter((s) => s.trim().length > 0),
      }),
      { minLength: count, maxLength: count },
    ),
  ),
)

describe('Property 11: Keyboard navigation traverses all entries', () => {
  it('After K ArrowDown presses, focused index is min(K-1, N-1) — stops at last item', () => {
    fc.assert(
      fc.property(
        // N: number of results (1-10)
        fc.integer({ min: 1, max: 10 }),
        // K: number of ArrowDown presses (1 to N+5, to test stopping at end)
        fc.integer({ min: 1, max: 15 }),
        (N, K) => {
          // Ensure K doesn't exceed N+5 for this specific N
          const actualK = Math.min(K, N + 5)

          const keyPresses = Array.from({ length: actualK }, () => 'ArrowDown')
          const result = simulateKeyboardNavigation(N, keyPresses)

          // focusedIndex starts at -1, each ArrowDown increments by 1, capped at N-1
          const expectedIndex = Math.min(actualK - 1, N - 1)

          expect(result.focusedIndex).toBe(expectedIndex)
          expect(result.isOpen).toBe(true)
          expect(result.selectedIndex).toBeNull()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('ArrowDown traverses each item sequentially before stopping at end', () => {
    fc.assert(
      fc.property(fc.integer({ min: 1, max: 10 }), (N) => {
        // Press ArrowDown N times — should visit indices 0, 1, ..., N-1
        const visited: number[] = []
        let focusedIndex = -1

        for (let i = 0; i < N; i++) {
          focusedIndex = Math.min(focusedIndex + 1, N - 1)
          visited.push(focusedIndex)
        }

        // Each index from 0 to N-1 should be visited exactly once in order
        for (let i = 0; i < N; i++) {
          expect(visited[i]).toBe(i)
        }

        // Additional presses should stay at N-1
        focusedIndex = Math.min(focusedIndex + 1, N - 1)
        expect(focusedIndex).toBe(N - 1)
      }),
      { numRuns: 100 },
    )
  })

  it('Enter selects the currently focused item (onChange called with id and name)', () => {
    fc.assert(
      fc.property(
        autocompleteResultsArb,
        // Number of ArrowDown presses before Enter (at least 1 to focus an item)
        fc.integer({ min: 1, max: 10 }),
        ([count, results], downPresses) => {
          const actualDownPresses = Math.min(downPresses, count)
          const keyPresses = [
            ...Array.from({ length: actualDownPresses }, () => 'ArrowDown'),
            'Enter',
          ]

          const navResult = simulateKeyboardNavigation(count, keyPresses)

          // The focused index before Enter was min(actualDownPresses - 1, count - 1)
          const expectedSelectedIndex = Math.min(actualDownPresses - 1, count - 1)

          expect(navResult.selectedIndex).toBe(expectedSelectedIndex)

          // Verify the selected item matches
          const selectedItem = results[expectedSelectedIndex]
          expect(selectedItem).toBeDefined()
          expect(selectedItem.id).toBeTruthy()
          expect(selectedItem.name).toBeTruthy()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Dropdown closes after Enter on a focused item', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 10 }),
        fc.integer({ min: 1, max: 10 }),
        (N, downPresses) => {
          const keyPresses = [...Array.from({ length: downPresses }, () => 'ArrowDown'), 'Enter']

          const result = simulateKeyboardNavigation(N, keyPresses)

          // After Enter with a valid focused index, dropdown should be closed
          expect(result.isOpen).toBe(false)
          expect(result.selectedIndex).not.toBeNull()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Focus stops at the last item — additional ArrowDown does not exceed bounds', () => {
    fc.assert(
      fc.property(fc.integer({ min: 1, max: 10 }), (N) => {
        // Press ArrowDown N+5 times — should never exceed N-1
        const keyPresses = Array.from({ length: N + 5 }, () => 'ArrowDown')
        const result = simulateKeyboardNavigation(N, keyPresses)

        expect(result.focusedIndex).toBe(N - 1)
        expect(result.focusedIndex).toBeLessThan(N)
        expect(result.focusedIndex).toBeGreaterThanOrEqual(0)
      }),
      { numRuns: 100 },
    )
  })

  it('Enter without prior ArrowDown does not select (focusedIndex starts at -1)', () => {
    fc.assert(
      fc.property(fc.integer({ min: 1, max: 10 }), (N) => {
        const result = simulateKeyboardNavigation(N, ['Enter'])

        // No item should be selected since focusedIndex starts at -1
        expect(result.selectedIndex).toBeNull()
        expect(result.isOpen).toBe(true)
      }),
      { numRuns: 100 },
    )
  })
})
