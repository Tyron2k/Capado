/** Mounted edit forms must keep the displayed selection and submitted identity together. */
import { beforeAll, beforeEach, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'
import { createTestQueryClient } from '../../testUtils/queryClient'
import { I18nProvider } from '../../i18n'
import type { Assignment } from '../../types/assignment'
import { AssignmentForm } from './AssignmentForm'
import { getProjects } from '../../api/projects'
import { getWorkPackages } from '../../api/workPackages'
import { searchAutocomplete } from '../../api/autocomplete'

vi.mock('../../api/projects', () => ({ getProjects: vi.fn() }))
vi.mock('../../api/workPackages', () => ({ getWorkPackages: vi.fn() }))
vi.mock('../../api/autocomplete', () => ({ searchAutocomplete: vi.fn() }))
vi.mock('./SuggestionList', () => ({ SuggestionList: () => null }))

const first: Assignment = {
  id: 'assignment-a',
  resource_id: 'person-a',
  resource_name: 'Person A',
  resource_type: 'personal',
  project_id: 'project-a',
  project_name: 'Project A',
  work_package_id: 'package-a',
  work_package_name: 'Package A',
  start_date: '2026-10-05',
  end_date: '2026-10-09',
  allocation_percent: 60,
  start_at: null,
  end_at: null,
  skill_mismatch: false,
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z',
}

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  window.matchMedia = vi
    .fn()
    .mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getProjects).mockResolvedValue(
    ['a', 'b'].map((suffix) => ({
      id: `project-${suffix}`,
      name: `Project ${suffix.toUpperCase()}`,
      folder_id: null,
      position: 0,
      external_ref: null,
      committed_delivery_date: null,
      customer_id: null,
      customer_name: null,
      customer_inherited: false,
      priority: 'normal',
      start_date: '2026-10-01',
      end_date: '2026-10-31',
      created_at: first.created_at,
      updated_at: first.updated_at,
    })),
  )
  vi.mocked(getWorkPackages).mockImplementation(async (projectId) => [
    {
      id: projectId.replace('project', 'package'),
      project_id: projectId,
      name: projectId.replace('project-', 'Package ').toUpperCase(),
      start_date: '2026-10-05',
      end_date: '2026-10-09',
      completed_at: null,
      lead_time_working_days: null,
      created_at: first.created_at,
      updated_at: first.updated_at,
    },
  ])
  vi.mocked(searchAutocomplete).mockResolvedValue([])
})

it.each(['same-project', 'another-project-and-type', 'pending-blur'] as const)(
  'updates selection when the mounted assignment changes: %s',
  async (mode) => {
    const client = createTestQueryClient()
    const onSubmit = vi.fn()
    const view = (assignment: Assignment) => (
      <QueryClientProvider client={client}>
        <MantineProvider env="test">
          <I18nProvider locale="en">
            <AssignmentForm assignment={assignment} onSubmit={onSubmit} onCancel={vi.fn()} />
          </I18nProvider>
        </MantineProvider>
      </QueryClientProvider>
    )
    const { rerender } = render(view(first))
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: /^Resource/ })).toHaveValue('Person A'),
    )
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Project' })).toHaveValue('Project A'),
    )
    const second: Assignment =
      mode !== 'another-project-and-type'
        ? { ...first, id: 'assignment-b', resource_id: 'person-b', resource_name: 'Person B' }
        : {
            ...first,
            id: 'assignment-b',
            resource_id: 'station-b',
            resource_name: 'Station B',
            resource_type: 'infrastructure',
            project_id: 'project-b',
            project_name: 'Project B',
            work_package_id: 'package-b',
            work_package_name: 'Package B',
            start_date: null,
            end_date: null,
            allocation_percent: null,
            start_at: '2026-10-06T06:00:00Z',
            end_at: '2026-10-06T10:00:00Z',
          }
    if (mode === 'pending-blur') {
      // A delayed blur from the previous search must not clear the next record's ID.
      fireEvent.change(screen.getByRole('combobox', { name: /^Resource/ }), {
        target: { value: 'Old draft' },
      })
      vi.useFakeTimers()
      try {
        fireEvent.blur(screen.getByRole('combobox', { name: /^Resource/ }))
        rerender(view(second))
        await act(async () => {
          await vi.advanceTimersByTimeAsync(200)
        })
      } finally {
        vi.useRealTimers()
      }
    } else {
      rerender(view(second))
    }
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: /^Resource/ })).toHaveValue(second.resource_name),
    )
    if (mode !== 'another-project-and-type') {
      await waitFor(() =>
        expect(screen.getByRole('textbox', { name: /^Start Date/ })).toHaveValue('05.10.2026'),
      )
    }
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Project' })).toHaveValue(second.project_name),
    )
    // Submit the actual form handler, including IDs and resource-type date validation.
    fireEvent.submit(screen.getByRole('button', { name: 'Save' }).closest('form')!)
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmit.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        resource_id: second.resource_id,
        resource_type: second.resource_type,
        work_package_id: second.work_package_id,
      }),
    )
    // A plain rerender of the same record must not overwrite a user search draft.
    const resource = screen.getByRole('combobox', { name: /^Resource/ })
    fireEvent.change(resource, { target: { value: 'Another' } })
    rerender(view(second))
    expect(resource).toHaveValue('Another')
  },
)
