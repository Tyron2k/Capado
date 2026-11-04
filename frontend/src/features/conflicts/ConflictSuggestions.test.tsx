// @vitest-environment jsdom

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'

vi.mock('../../api/assignments', () => ({
  getAssignment: vi.fn(),
  getAssignmentSuggestions: vi.fn(),
  getConflictSuggestions: vi.fn(),
  previewAssignment: vi.fn(),
  updateAssignment: vi.fn(),
}))
vi.mock('@mantine/notifications', () => ({ notifications: { show: vi.fn() } }))
vi.mock('../../utils/errorHandling', () => ({ showErrorNotification: vi.fn() }))

import {
  getAssignment,
  getAssignmentSuggestions,
  getConflictSuggestions,
  previewAssignment,
  updateAssignment,
} from '../../api/assignments'
import { I18nProvider } from '../../i18n'
import { createTestQueryClient } from '../../testUtils/queryClient'
import { ConflictSuggestions } from './ConflictSuggestions'

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  })
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

const assignment = {
  project_id: null,
  project_name: null,
  resource_name: null,
  work_package_name: null,
  id: 'a1',
  resource_id: 'r1',
  resource_type: 'personal' as const,
  work_package_id: 'w1',
  start_date: '2026-09-01',
  end_date: '2026-09-10',
  allocation_percent: 80,
  start_at: null,
  end_at: null,
  skill_mismatch: false,
  created_at: '2026-08-01T00:00:00',
  updated_at: '2026-08-01T00:00:00',
}

const preview = {
  resources: [
    {
      resource_id: 'r1',
      resource_name: 'Test Resource',
      resource_type: 'personal' as const,
      conflicts_before: [],
      conflicts_after: [],
      capacity_days: [],
    },
  ],
}

function renderSuggestions(assignmentIds?: string[]) {
  const onApplied = vi.fn()
  render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MantineProvider env="test">
        <I18nProvider locale="de">
          <ConflictSuggestions
            {...(assignmentIds ? { assignmentIds } : { conflictId: 'c1' })}
            onApplied={onApplied}
          />
        </I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
  return onApplied
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getConflictSuggestions).mockResolvedValue([
    {
      conflicts_before: null,
      conflicts_after: null,
      work_package_name: null,
      new_allocation_percent: null,
      new_end_at: null,
      new_start_at: null,
      target_resource_id: null,
      target_resource_name: null,
      type: 'shift_forward',
      assignment_id: 'a1',
      description: 'shift',
      shift_days: 2,
    },
  ])
  vi.mocked(getAssignment).mockResolvedValue(assignment)
  vi.mocked(previewAssignment).mockResolvedValue(preview)
  vi.mocked(updateAssignment).mockResolvedValue({ assignment, warnings: [] })
})

describe('conflict suggestions in the planning overview', () => {
  it('shows the impact without writing, then applies the same shift after confirmation', async () => {
    const onApplied = renderSuggestions()
    fireEvent.click(await screen.findByRole('button', { name: 'Vorschau' }))

    expect(await screen.findByText('Konflikte: 0 → 0')).toBeInTheDocument()
    const change = screen.getByRole('table', { name: 'Geplante Änderung' })
    const start = within(change).getByRole('row', { name: /Startdatum/ })
    expect(within(start).getByText('01.09.2026')).toBeVisible()
    expect(within(start).getByText('03.09.2026')).toBeVisible()
    expect(within(start).getByText('Geändert')).toBeVisible()
    const allocation = within(change).getByRole('row', { name: /Auslastung/ })
    expect(within(allocation).getAllByText('80 %')).toHaveLength(2)
    expect(within(allocation).getByText('Unverändert')).toBeVisible()
    expect(getAssignment).toHaveBeenCalledWith('a1')
    expect(previewAssignment).toHaveBeenCalledWith(
      expect.objectContaining({
        assignment_id: 'a1',
        start_date: '2026-09-03',
        end_date: '2026-09-12',
      }),
    )
    expect(updateAssignment).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Anwenden' }))
    await waitFor(() =>
      expect(updateAssignment).toHaveBeenCalledWith('a1', {
        start_date: '2026-09-03',
        end_date: '2026-09-12',
      }),
    )
    await waitFor(() => expect(onApplied).toHaveBeenCalledOnce())
  })

  it('closes the preview without changing the plan', async () => {
    renderSuggestions()
    fireEvent.click(await screen.findByRole('button', { name: 'Vorschau' }))
    expect(await screen.findByText('Konflikte: 0 → 0')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Abbrechen' }))
    expect(updateAssignment).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Anwenden' })).not.toBeInTheDocument()
  })
})

it('distinguishes an empty result from a failed request and offers a retry', async () => {
  vi.mocked(getConflictSuggestions)
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValue([])
  renderSuggestions()
  expect(await screen.findByText(/Die Vorschläge konnten nicht geladen werden/)).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }))
  expect(await screen.findByText(/Keine automatische Lösung gefunden/)).toBeVisible()
  expect(screen.queryByText(/Die Vorschläge konnten nicht geladen werden/)).not.toBeInTheDocument()
})

it('shows the exact allocation reduction before saving the same value', async () => {
  vi.mocked(getConflictSuggestions).mockResolvedValue([
    {
      conflicts_before: null,
      conflicts_after: null,
      work_package_name: null,
      type: 'reduce_allocation',
      assignment_id: 'a1',
      description: 'reduce',
      new_allocation_percent: 37.5,
      new_end_at: null,
      new_start_at: null,
      target_resource_id: null,
      target_resource_name: null,
      shift_days: null,
    },
  ])
  renderSuggestions()
  fireEvent.click(await screen.findByRole('button', { name: 'Vorschau' }))
  const table = await screen.findByRole('table', { name: 'Geplante Änderung' })
  const allocation = within(table).getByRole('row', { name: /Auslastung/ })
  expect(within(allocation).getByText('80 %')).toBeVisible()
  expect(within(allocation).getByText('37,5 %')).toBeVisible()
  expect(within(allocation).getByText('Geändert')).toBeVisible()
  expect(within(table).getByRole('row', { name: /Startdatum/ })).toHaveTextContent('Unverändert')
  expect(updateAssignment).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Anwenden' }))
  await waitFor(() =>
    expect(updateAssignment).toHaveBeenCalledWith('a1', { allocation_percent: 37.5 }),
  )
})

it('ranks every involved booking by remaining conflicts, with unknown effects last', async () => {
  const base = {
    type: 'shift_forward' as const,
    assignment_id: 'a1',
    description: 'shift',
    shift_days: 2,
    new_allocation_percent: null,
    new_end_at: null,
    new_start_at: null,
    target_resource_id: null,
    target_resource_name: null,
    conflicts_before: 2,
  }
  vi.mocked(getAssignmentSuggestions).mockImplementation(async (id) =>
    id === 'a1'
      ? [
          { ...base, work_package_name: 'Partial fix', conflicts_after: 1 },
          { ...base, work_package_name: 'Unknown effect', conflicts_after: null },
        ]
      : [{ ...base, assignment_id: 'a2', work_package_name: 'Complete fix', conflicts_after: 0 }],
  )
  renderSuggestions(['a1', 'a2'])
  expect(await screen.findByText('0 verbleibend')).toBeVisible()
  expect(screen.getByText('1 verbleibend')).toBeVisible()
  expect(screen.getByText('Wirkung nicht prüfbar')).toBeVisible()
  expect(getAssignmentSuggestions).toHaveBeenCalledWith('a1', false)
  expect(getAssignmentSuggestions).toHaveBeenCalledWith('a2', false)
  const names = screen
    .getAllByText(/^(Complete fix|Partial fix|Unknown effect)$/)
    .map((node) => node.textContent)
  expect(names).toEqual(['Complete fix', 'Partial fix', 'Unknown effect'])
  expect(previewAssignment).not.toHaveBeenCalled()
  expect(updateAssignment).not.toHaveBeenCalled()
})
