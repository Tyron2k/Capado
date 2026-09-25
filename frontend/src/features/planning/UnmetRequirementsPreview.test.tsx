// @vitest-environment jsdom

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'

vi.mock('../../api/assignments', () => ({
  createAssignment: vi.fn(),
  previewAssignment: vi.fn(),
}))
vi.mock('@mantine/notifications', () => ({ notifications: { show: vi.fn() } }))
vi.mock('../../utils/errorHandling', () => ({ showErrorNotification: vi.fn() }))

import { createAssignment, previewAssignment } from '../../api/assignments'
import { I18nProvider } from '../../i18n'
import { createTestQueryClient } from '../../testUtils/queryClient'
import type { UnmetRequirement } from '../../types/assignment'
import { UnmetRequirementsSection } from './UnmetRequirementsAlert'

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

function requirement(resourceType: 'personal' | 'infrastructure'): UnmetRequirement {
  return {
    work_package_id: 'w1',
    work_package_name: 'Test Package',
    project_id: 'p1',
    project_name: 'Test Project',
    start_date: '2026-09-01',
    end_date: '2026-09-10',
    skill_name: 'Test Skill',
    attribute_name: null,
    resource_type: resourceType,
    required_quantity: 1,
    assigned_quantity: 0,
    gap: 1,
    suggestions: [
      {
        resource_id: 'r1',
        resource_name: 'Test Resource',
        resource_type: resourceType,
        group_name: null,
        overlapping_assignments: 0,
      },
    ],
  }
}

function renderSection(resourceType: 'personal' | 'infrastructure') {
  const onAssigned = vi.fn()
  render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MantineProvider env="test">
        <I18nProvider locale="de">
          <UnmetRequirementsSection
            items={[requirement(resourceType)]}
            title="Offene Anforderungen"
            error={false}
            onAssigned={onAssigned}
          />
        </I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
  fireEvent.click(screen.getByTestId('unmet-wp-w1'))
  return onAssigned
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(previewAssignment).mockResolvedValue({
    resources: [
      {
        resource_id: 'r1',
        resource_name: 'Test Resource',
        resource_type: 'personal',
        conflicts_before: [],
        conflicts_after: [],
        capacity_days: [],
      },
    ],
  })
  vi.mocked(createAssignment).mockResolvedValue({ assignment: {} as never, warnings: [] })
})

describe('unmet requirement suggestions', () => {
  it('previews a personal assignment before assigning it', async () => {
    const onAssigned = renderSection('personal')
    fireEvent.click(await screen.findByRole('button', { name: 'Vorschau' }))

    expect(await screen.findByText('Konflikte: 0 → 0')).toBeInTheDocument()
    expect(previewAssignment).toHaveBeenCalledWith({
      resource_id: 'r1',
      work_package_id: 'w1',
      resource_type: 'personal',
      start_date: '2026-09-01',
      end_date: '2026-09-10',
      allocation_percent: 100,
    })
    expect(createAssignment).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Zuweisen' }))
    await waitFor(() =>
      expect(createAssignment).toHaveBeenCalledWith(vi.mocked(previewAssignment).mock.calls[0][0]),
    )
    await waitFor(() => expect(onAssigned).toHaveBeenCalledOnce())
  })

  it('previews an infrastructure booking with the same times used for creation', async () => {
    renderSection('infrastructure')
    fireEvent.click(await screen.findByRole('button', { name: 'Vorschau' }))

    expect(await screen.findByText('Konflikte: 0 → 0')).toBeInTheDocument()
    expect(previewAssignment).toHaveBeenCalledWith({
      resource_id: 'r1',
      work_package_id: 'w1',
      resource_type: 'infrastructure',
      start_at: '2026-09-01T08:00:00',
      end_at: '2026-09-10T17:00:00',
    })
    expect(createAssignment).not.toHaveBeenCalled()
  })

  it('cancels the preview without creating an assignment', async () => {
    renderSection('personal')
    fireEvent.click(await screen.findByRole('button', { name: 'Vorschau' }))
    expect(await screen.findByText('Konflikte: 0 → 0')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Abbrechen' }))
    expect(createAssignment).not.toHaveBeenCalled()
  })
})
