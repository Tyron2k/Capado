import { useState, useRef, useEffect } from 'react'

import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../api/queryClient'
import { TextInput, Paper, Text, Loader, Box } from '@mantine/core'
import { IconSearch } from '@tabler/icons-react'
import { searchAutocomplete } from '../api/autocomplete'
import type { AutocompleteResult } from '../types/resource'

interface AutocompleteFieldProps {
  type: 'personal' | 'infrastructure'
  label: string
  placeholder?: string
  value: string | null
  onChange: (id: string | null, name: string) => void
  required?: boolean
  error?: string
  noResultsMessage?: string
}

const DEBOUNCE_MS = 300
const TIMEOUT_MS = 5000

/**
 * Typeahead autocomplete field for searching resources.
 * Debounces input, supports keyboard navigation, and handles
 * network errors with timeout and abort controller cleanup.
 */
export function AutocompleteField({
  type,
  label,
  placeholder,
  value,
  onChange,
  required,
  error,
  noResultsMessage,
}: AutocompleteFieldProps) {
  const [inputValue, setInputValue] = useState('')
  const [focusedIndex, setFocusedIndex] = useState(-1)
  const [hasSelected, setHasSelected] = useState(false)

  const containerRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  // Sync input value when external value changes (e.g. form reset)
  useEffect(() => {
    if (value === null && !hasSelected) {
      setInputValue('')
    }
  }, [value, hasSelected])

  /**
   * A DEBOUNCED SEARCH TERM AS A KEY replaces a timer, an AbortController and a manual timeout.
   *
   * What this component hand-rolled: a debounce timer ref, an abort controller ref, a `cancelPendingRequest`
   * that had to clear both, and a 5-second `setTimeout` racing the request so a hanging call could not
   * leave the spinner up forever. Every one of those had to be cleaned up on unmount and on each new
   * keystroke, and a missed path leaked either a stuck spinner or a late response overwriting a newer one.
   *
   * Keying on the debounced term removes the whole apparatus: a new term is a new key, so the previous
   * request is superseded rather than cancelled by hand, and a late answer lands under its own key where
   * nothing renders it. What is GAINED is that backspacing and retyping a term answers from cache — the
   * single most common thing anyone does in an autocomplete, and previously a fresh request every time.
   *
   * The 5s timeout is kept as `AbortSignal.timeout`, which is the same guarantee expressed as the request's
   * own deadline rather than as a race between two timers.
   */
  const [debouncedTerm, setDebouncedTerm] = useState('')

  useEffect(() => {
    const term = inputValue.trim()
    if (!term) {
      setDebouncedTerm('')
      return
    }
    const timer = setTimeout(() => setDebouncedTerm(term), DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [inputValue])

  const searchQuery = useQuery({
    queryKey: queryKeys.autocomplete.search(type, debouncedTerm),
    queryFn: () =>
      searchAutocomplete({ q: debouncedTerm, type, signal: AbortSignal.timeout(TIMEOUT_MS) }),
    enabled: debouncedTerm.length > 0 && !hasSelected,
  })

  const results: AutocompleteResult[] = searchQuery.data ?? []
  const isLoading = debouncedTerm.length > 0 && !hasSelected && searchQuery.isPending
  // Kept as a literal English string, exactly as before. Localising it is a separate change and pretending
  // otherwise here would hide it: this component predates the i18n dictionary covering it.
  const networkError = searchQuery.error ? 'Connection problem — please try again' : null

  /**
   * WHETHER THE DROPDOWN IS SHOWN IS CLIENT STATE; what it contains is server state. Splitting them is
   * the point, and collapsing them would be the mistake.
   *
   * The list is DERIVED from having results, so an answer no longer "decides" to open the popup — which
   * previously meant a response landing after the user had picked something could reopen a closed list.
   * But dismissal is a user act, not a data fact: Escape and blur must close a list that still has
   * results in it. So `dismissed` is real state, and typing clears it.
   */
  const [dismissed, setDismissed] = useState(false)
  const isOpen = !hasSelected && !dismissed && results.length > 0 && debouncedTerm.length > 0

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = event.currentTarget.value
    setInputValue(newValue)
    setHasSelected(false)
    setDismissed(false)

    // Clearing the field clears the selection. The search stops on its own: an empty term disables the
    // query, so there is nothing left to cancel.
    if (!newValue.trim()) {
      onChange(null, '')
    }
  }

  const handleSelect = (result: AutocompleteResult) => {
    setInputValue(result.name)
    // Closes the list and stops the search in one flag: `isOpen` and the query's `enabled` both read it,
    // so a picked value cannot be followed by a late response reopening the dropdown.
    setHasSelected(true)
    setFocusedIndex(-1)
    onChange(result.id, result.name)
  }

  const handleBlur = () => {
    // Delay to allow click on dropdown items
    setTimeout(() => {
      if (!containerRef.current?.contains(document.activeElement)) {
        setDismissed(true)
        setFocusedIndex(-1)
        if (!hasSelected) {
          onChange(null, '')
        }
      }
    }, 200)
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (!isOpen || results.length === 0) {
      return
    }

    switch (event.key) {
      case 'ArrowDown': {
        event.preventDefault()
        setFocusedIndex((prev) => Math.min(prev + 1, results.length - 1))
        break
      }
      case 'ArrowUp': {
        event.preventDefault()
        setFocusedIndex((prev) => Math.max(prev - 1, 0))
        break
      }
      case 'Enter': {
        event.preventDefault()
        if (focusedIndex >= 0 && focusedIndex < results.length) {
          handleSelect(results[focusedIndex])
        }
        break
      }
      case 'Escape': {
        event.preventDefault()
        setDismissed(true)
        setFocusedIndex(-1)
        break
      }
    }
  }

  // Scroll focused item into view
  useEffect(() => {
    if (focusedIndex >= 0 && listRef.current) {
      const items = listRef.current.querySelectorAll('[data-autocomplete-item]')
      const focusedItem = items[focusedIndex]
      if (focusedItem) {
        focusedItem.scrollIntoView({ block: 'nearest' })
      }
    }
  }, [focusedIndex])

  // No cleanup effect: the debounce timer clears itself in its own effect, and the request's deadline is
  // the signal passed to it. There is nothing left that outlives the component.

  return (
    <Box ref={containerRef} style={{ position: 'relative' }}>
      <TextInput
        label={label}
        placeholder={placeholder}
        value={inputValue}
        onChange={handleInputChange}
        onKeyDown={handleKeyDown}
        onBlur={handleBlur}
        required={required}
        error={error || networkError}
        leftSection={<IconSearch size={16} />}
        rightSection={isLoading ? <Loader size="xs" /> : undefined}
        autoComplete="off"
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-autocomplete="list"
        role="combobox"
      />

      {isOpen && (
        <Paper
          ref={listRef}
          shadow="md"
          withBorder
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            zIndex: 1000,
            maxHeight: 300,
            overflowY: 'auto',
          }}
          role="listbox"
        >
          {results.length === 0 ? (
            <Box p="sm">
              <Text size="sm" c="dimmed" ta="center">
                {noResultsMessage || 'No matching entries found'}
              </Text>
            </Box>
          ) : (
            results.map((result, index) => (
              <Box
                key={result.id}
                data-autocomplete-item
                p="xs"
                px="sm"
                style={{
                  cursor: 'pointer',
                  backgroundColor:
                    index === focusedIndex ? 'var(--mantine-color-blue-light)' : undefined,
                }}
                onMouseDown={(e) => {
                  e.preventDefault() // Prevent blur before selection
                  handleSelect(result)
                }}
                onMouseEnter={() => setFocusedIndex(index)}
                role="option"
                aria-selected={index === focusedIndex}
              >
                <Text size="sm" fw={500}>
                  {result.name}
                </Text>
                <Text size="xs" c="dimmed">
                  {result.detail}
                </Text>
              </Box>
            ))
          )}
        </Paper>
      )}
    </Box>
  )
}
