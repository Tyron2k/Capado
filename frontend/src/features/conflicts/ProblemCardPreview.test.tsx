// @vitest-environment jsdom

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'

vi.mock('../../api/assignments', () => ({
  getAssignment: vi.fn(),
  previewAssignment: vi.fn(),
  updateAssignment: vi.fn(),
}))
vi.mock('../../api/suggestions', () => ({ getSuggestions: vi.fn() }))
vi.mock('../../api/workPackages', () => ({ getWorkPackageRequirements: vi.fn() }))
vi.mock('../../api/skills', () => ({ searchByQualification: vi.fn() }))
vi.mock('./ConflictAssignmentList', () => ({ ConflictAssignmentList: () => <div /> }))
vi.mock('@mantine/notifications', () => ({ notifications: { show: vi.fn() } }))
vi.mock('../../utils/errorHandling', () => ({ showErrorNotification: vi.fn() }))

import { getAssignment, previewAssignment, updateAssignment } from '../../api/assignments'
import { getSuggestions } from '../../api/suggestions'
import { getWorkPackageRequirements } from '../../api/workPackages'
import { searchByQualification } from '../../api/skills'
import { I18nProvider } from '../../i18n'
import { createTestQueryClient } from '../../testUtils/queryClient'
import { ProblemCard, type ProblemBucket } from './ProblemCard'

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
  resource_name: 'Original Resource',
  resource_type: 'personal' as const,
  work_package_id: 'w1',
  work_package_name: 'Test Package',
  start_date: '2026-09-01',
  end_date: '2026-09-10',
  allocation_percent: 80,
  start_at: null,
  end_at: null,
  skill_mismatch: true,
  created_at: '2026-08-01T00:00:00',
  updated_at: '2026-08-01T00:00:00',
}

const bucket: ProblemBucket = {
  type: 'skill',
  resource_id: 'r1',
  resource_name: 'Original Resource',
  resource_type: 'personal',
  assignments: [{ assignment_id: 'a1', work_package_name: 'Test Package' }],
  rawAssignments: [assignment],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getWorkPackageRequirements).mockResolvedValue([
    {
      id: 'req1',
      skill_id: 'skill1',
      skill_name: 'Skill One',
      skill_attribute_id: null,
      skill_attribute_name: null,
      quantity: 1,
    },
  ])
  vi.mocked(getSuggestions).mockResolvedValue([
    {
      resource_id: 'r2',
      resource_name: 'Replacement Resource',
      qualification_summary: 'Skill One',
      department: 'Test',
      availability_status: 'available',
      average_free_capacity: 100,
      reason: '',
    },
  ])
  vi.mocked(searchByQualification).mockResolvedValue([{ id: 'r2' } as never])
  vi.mocked(getAssignment).mockResolvedValue(assignment)
  vi.mocked(previewAssignment).mockResolvedValue({
    resources: [
      {
        resource_id: 'r2',
        resource_name: 'Replacement Resource',
        resource_type: 'personal',
        conflicts_before: [],
        conflicts_after: [],
        capacity_days: [],
      },
    ],
  })
  vi.mocked(updateAssignment).mockResolvedValue({ assignment, warnings: [] })
})

describe('skill-conflict resource swap', () => {
  it('requires a capacity preview before applying the replacement', async () => {
    const onChanged = vi.fn()
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <MantineProvider env="test">
          <I18nProvider locale="de">
            <ProblemCard bucket={bucket} onChanged={onChanged} />
          </I18nProvider>
        </MantineProvider>
      </QueryClientProvider>,
    )

    fireEvent.click(screen.getByText('Original Resource'))
    const previewButton = await screen.findByRole('button', {
      name: 'Vorschau — Ressource tauschen',
    })
    expect(getSuggestions).toHaveBeenCalledWith(expect.objectContaining({ work_package_id: 'w1' }))
    expect(previewButton.textContent).toBe('Vorschau')
    fireEvent.click(previewButton)
    expect(await screen.findByText('Konflikte: 0 → 0')).toBeInTheDocument()
    expect(previewAssignment).toHaveBeenCalledWith(
      expect.objectContaining({
        assignment_id: 'a1',
        resource_id: 'r2',
      }),
    )
    expect(updateAssignment).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Anwenden' }))
    await waitFor(() => expect(updateAssignment).toHaveBeenCalledWith('a1', { resource_id: 'r2' }))
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce())
  })
})
