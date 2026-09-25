/**
 * WHERE THE QUERY LAYER STOPS — the boundary the last batch had to draw, and the reason the migration's
 * own measurement command could not be trusted to declare itself finished.
 *
 * The command looked for `setLoading`, `await get` and `.then(` in `features/`. Three things hid from it:
 *
 *   A file that only WRITES. ConflictResolutionActions has five assignment writes -- the most
 *   consequential in the product, made from the screen whose purpose is to fix a conflict -- and no reads
 *   at all. It spells its pending flag `setSaving`. A grep for hand-rolled reads cannot see it.
 *
 *   A file outside `features/`. RequirementsEditor held a module-level cache with promise deduplication,
 *   described in its own comment as cached "for the session lifetime". It was a cache, correctly
 *   deduplicated, and it could not GO STALE -- so adding a skill left every requirements editor offering
 *   the old catalogue, and the skill somebody had just created in order to require it was the one thing
 *   they could not pick.
 *
 *   A different spelling. AutocompleteField and SuggestionList used `setIsLoading`.
 *
 * These tests pin the two ends of the boundary: a command invalidates NOTHING because there is nothing to
 * invalidate, and a conflict resolution invalidates the whole plan including the charts that draw it.
 */
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/assignments', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/assignments')>()),
  updateAssignment: vi.fn(),
  deleteAssignment: vi.fn(),
}))

const showErrorNotification = vi.fn()
vi.mock('../../utils/errorHandling', () => ({
  showErrorNotification: (...args: unknown[]) => showErrorNotification(...args),
}))

vi.mock('@mantine/notifications', () => ({ notifications: { show: vi.fn() } }))

import { deleteAssignment, updateAssignment } from '../../api/assignments'
import { queryKeys } from '../../api/queryClient'
import { createTestQueryClient, trackInvalidations } from '../../testUtils/queryClient'
import { I18nProvider } from '../../i18n'
import { ConflictResolutionActions } from './ConflictResolutionActions'

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
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  window.confirm = vi.fn(() => true)
})

const assignment = {
  assignment_id: 'a1',
  resource_id: 'r1',
  resource_name: 'A. Beispiel',
  resource_type: 'personal',
  work_package_name: 'Demontage',
  project_name: 'Baureihe 4T',
  start_date: '2026-09-01',
  end_date: '2026-09-10',
  start_at: null,
  end_at: null,
  allocation_percent: 100,
  overload_ratio: 1.4,
} as never

function renderActions() {
  const client = createTestQueryClient()
  const invalidated = trackInvalidations(client)
  const onChanged = vi.fn()
  const view = render(
    <QueryClientProvider client={client}>
      <MantineProvider env="test">
        <I18nProvider locale="de">
          <ConflictResolutionActions assignment={assignment} onChanged={onChanged} />
        </I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
  return { ...view, invalidated, onChanged }
}

beforeEach(() => {
  vi.mocked(updateAssignment).mockReset()
  vi.mocked(deleteAssignment).mockReset()
  showErrorNotification.mockReset()
})

describe('resolving a conflict writes the plan', () => {
  it('declares the plan AND the charts that draw it untrue', async () => {
    vi.mocked(deleteAssignment).mockResolvedValue(undefined)

    const { invalidated, onChanged } = renderActions()
    expect(screen.getByTestId('resolution-open').textContent).toBe('Aktionen')
    fireEvent.click(screen.getByTestId('resolution-open'))
    await waitFor(() => expect(screen.getByTestId('resolution-delete')).toBeTruthy())
    fireEvent.click(screen.getByTestId('resolution-delete'))

    await waitFor(() => expect(deleteAssignment).toHaveBeenCalledWith('a1'))
    await waitFor(() => {
      for (const key of [
        queryKeys.assignments.all,
        queryKeys.conflicts.all,
        queryKeys.planning.all,
        queryKeys.digest.all,
        queryKeys.resources.all,
        // The one this card adds over the assignments panel: a conflict is resolved by moving a bar,
        // and the Gantt charts draw that bar. Previously `onChanged()` was the only refresh, so what
        // got updated depended on which parent had rendered the card.
        queryKeys.gantt.all,
      ]) {
        expect(invalidated).toContainEqual([...key])
      }
    })

    // Still called: the parent uses it to collapse the card, which is presentation, not data.
    expect(onChanged).toHaveBeenCalled()
  })

  it('invalidates nothing when the write fails', async () => {
    vi.mocked(deleteAssignment).mockRejectedValue(new Error('boom'))

    const { invalidated, onChanged } = renderActions()
    fireEvent.click(screen.getByTestId('resolution-open'))
    await waitFor(() => expect(screen.getByTestId('resolution-delete')).toBeTruthy())
    fireEvent.click(screen.getByTestId('resolution-delete'))

    await waitFor(() => expect(showErrorNotification).toHaveBeenCalledTimes(1))
    expect(invalidated).toEqual([])
    // Nor is the parent told the card is done with: nothing happened.
    expect(onChanged).not.toHaveBeenCalled()
  })

  it('does not touch the server for a validation mistake', async () => {
    const { invalidated } = renderActions()
    fireEvent.click(screen.getByTestId('resolution-open'))
    await waitFor(() => expect(screen.getByTestId('resolution-reduce-open')).toBeTruthy())
    fireEvent.click(screen.getByTestId('resolution-reduce-open'))
    await waitFor(() => expect(screen.getByTestId('resolution-reduce-confirm')).toBeTruthy())

    // The percent field starts empty, so confirming is a validation mistake rather than a write.
    fireEvent.click(screen.getByTestId('resolution-reduce-confirm'))

    expect(updateAssignment).not.toHaveBeenCalled()
    expect(invalidated).toEqual([])
  })
})
