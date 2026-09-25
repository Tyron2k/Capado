// @vitest-environment jsdom

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'

vi.mock('../../api/assignments', () => ({
  getAssignment: vi.fn(),
  getConflictSuggestions: vi.fn(),
  previewAssignment: vi.fn(),
  updateAssignment: vi.fn(),
}))
vi.mock('@mantine/notifications', () => ({ notifications: { show: vi.fn() } }))
vi.mock('../../utils/errorHandling', () => ({ showErrorNotification: vi.fn() }))

import {
  getAssignment,
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

function renderSuggestions() {
  const onApplied = vi.fn()
  render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MantineProvider env="test">
        <I18nProvider locale="de">
          <ConflictSuggestions conflictId="c1" onApplied={onApplied} />
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
