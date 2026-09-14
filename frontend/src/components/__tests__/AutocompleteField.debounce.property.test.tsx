/**
 * Property-Based Test: Debounce prevents multiple requests
 *
 * Feature: ressourcen-hierarchien-und-autocomplete, Property 9: Debounce prevents multiple requests
 *
 * For any sequence of keystrokes typed within 300ms, exactly one request is sent
 * to the Autocomplete_Service (after 300ms of inactivity), and the request uses
 * the final input value.
 */

// @vitest-environment jsdom

import { describe, it, expect, vi, beforeEach, afterEach, beforeAll } from 'vitest'
import { QueryClientProvider } from '@tanstack/react-query'

import { createTestQueryClient } from '../../testUtils/queryClient'
import * as fc from 'fast-check'
import React from 'react'
import { render, fireEvent, act } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { AutocompleteField } from '../AutocompleteField'

// Mock window.matchMedia for Mantine
beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
})

// Mock the searchAutocomplete API function
vi.mock('../../api/autocomplete', () => ({
  searchAutocomplete: vi.fn(),
}))

// Import the mocked function for assertions
import { searchAutocomplete } from '../../api/autocomplete'

const mockedSearchAutocomplete = vi.mocked(searchAutocomplete)

// --- Generators ---

/**
 * Generates a sequence of single alphanumeric characters (length 1-10).
 * Each represents a keystroke typed rapidly within 300ms.
 */
const keystrokeSequenceArb = fc.array(
  fc.constantFrom(
    'a',
    'b',
    'c',
    'd',
    'e',
    'f',
    'g',
    'h',
    'i',
    'j',
    'k',
    'l',
    'm',
    'n',
    'o',
    'p',
    'q',
    'r',
    's',
    't',
    'u',
    'v',
    'w',
    'x',
    'y',
    'z',
    '0',
    '1',
    '2',
    '3',
  ),
  { minLength: 1, maxLength: 10 },
)

// --- Helper ---

function renderWithMantine(ui: React.ReactElement) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MantineProvider>{ui}</MantineProvider>
    </QueryClientProvider>,
  )
}

// --- Property Test ---

describe('Feature: ressourcen-hierarchien-und-autocomplete, Property 9: Debounce prevents multiple requests', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockedSearchAutocomplete.mockReset()
    mockedSearchAutocomplete.mockResolvedValue([])
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('for input sequences within 300ms, exactly one request is sent', () => {
    fc.assert(
      fc.property(keystrokeSequenceArb, (keystrokes) => {
        mockedSearchAutocomplete.mockReset()
        mockedSearchAutocomplete.mockResolvedValue([])

        const onChange = vi.fn()

        const { getByRole, unmount } = renderWithMantine(
          <AutocompleteField type="personal" label="Test" value={null} onChange={onChange} />,
        )

        const input = getByRole('combobox')

        // Simulate typing each keystroke rapidly (all within 300ms)
        // Each keystroke appends to the current value, simulating real typing
        let currentValue = ''
        for (const char of keystrokes) {
          currentValue += char
          act(() => {
            fireEvent.change(input, { target: { value: currentValue } })
          })
          // Advance time by a small amount (< 300ms total for all keystrokes)
          // Each keystroke is ~20ms apart, ensuring all are within debounce window
          act(() => {
            vi.advanceTimersByTime(20)
          })
        }

        // At this point, no request should have been sent yet
        // because each keystroke resets the 300ms debounce timer
        expect(mockedSearchAutocomplete).not.toHaveBeenCalled()

        // Now advance past the 300ms debounce period
        act(() => {
          vi.advanceTimersByTime(300)
        })

        // Exactly one request should have been made
        expect(mockedSearchAutocomplete).toHaveBeenCalledTimes(1)

        // The request should use the final input value (all keystrokes combined)
        const finalValue = keystrokes.join('')
        expect(mockedSearchAutocomplete).toHaveBeenCalledWith(
          expect.objectContaining({
            q: finalValue,
            type: 'personal',
          }),
        )

        unmount()
      }),
      { numRuns: 100 },
    )
  })
})
