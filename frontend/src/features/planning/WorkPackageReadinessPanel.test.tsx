import '@testing-library/jest-dom/vitest'
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { getPlanningOverview, getWorkPackageReadiness } from '../../api/assignments'
import type { components } from '../../api/generated/schema'
import { queryKeys } from '../../api/queryClient'
import { I18nProvider, type Locale } from '../../i18n'
import { createTestQueryClient } from '../../testUtils/queryClient'
import { WorkPackageReadinessPanel } from './WorkPackageReadinessPanel'
import { PlanningOverviewPanel } from './PlanningOverviewPanel'

vi.mock('../../api/assignments', async (original) => ({
  ...(await original<typeof import('../../api/assignments')>()),
  getWorkPackageReadiness: vi.fn(),
  getPlanningOverview: vi.fn(),
}))
vi.mock('../../context/SettingsContext', () => ({
  useSettings: () => ({ settings: { locale: 'en', timeZone: 'Europe/Berlin' } }),
}))
vi.mock('../../utils/errorHandling', () => ({ showErrorNotification: vi.fn() }))

type Readiness = components['schemas']['WorkPackageReadiness']
const wp = {
  id: 'wp',
  name: 'Assembly',
  project_id: 'p',
  project_name: 'Order A',
  start_date: '2099-01-05',
  end_date: '2099-01-07',
}
function evidence(changes: Partial<Readiness> = {}): Readiness {
  return {
    work_package: wp,
    checked_at: '2026-11-03T12:00:00Z',
    status: 'not_fully_assessable',
    personnel_status: 'covered',
    infrastructure_status: 'covered',
    qualification_status: 'covered',
    personnel_requirements: 1,
    infrastructure_requirements: 1,
    limits: ['personnel_clock_times', 'infrastructure_continuity'],
    supply_gaps: [],
    unmet_requirements: [],
    conflicts: [],
    assignments: [],
    ...changes,
  }
}
beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  })
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})
beforeEach(() => vi.resetAllMocks())
function setup({
  selected = 'wp' as string | null,
  locale = 'en' as Locale,
  client = createTestQueryClient(),
} = {}) {
  const onAssignments = vi.fn()
  const view = render(
    <QueryClientProvider client={client}>
      <MantineProvider>
        <I18nProvider locale={locale}>
          <WorkPackageReadinessPanel
            packages={[wp]}
            selected={selected}
            onSelect={vi.fn()}
            onAssignments={onAssignments}
            onChanged={vi.fn()}
          />
        </I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
  return { ...view, client, onAssignments }
}

describe('work package planning evidence', () => {
  it('does not run expensive checks until a work package is selected', () => {
    setup({ selected: null })
    expect(getWorkPackageReadiness).not.toHaveBeenCalled()
    expect(screen.getByRole('combobox', { name: 'Assess work package' })).toBeVisible()
    expect(screen.queryByTestId('work-package-readiness')).not.toBeInTheDocument()
  })

  it.each(['en', 'de'] as const)(
    'explains precision limits alongside covered dimensions in %s',
    async (locale) => {
      vi.mocked(getWorkPackageReadiness).mockResolvedValue(evidence())
      setup({ locale })
      expect(await screen.findByTestId('work-package-readiness')).toBeVisible()
      expect(
        screen.getByText(locale === 'en' ? 'Not fully assessable' : 'Nicht vollständig prüfbar'),
      ).toBeVisible()
      expect(
        screen.getAllByText(locale === 'en' ? 'Covered within scope' : 'Im Prüfumfang gedeckt'),
      ).toHaveLength(3)
      expect(
        screen.getByText(
          locale === 'en'
            ? /Shared presence during a particular machine shift/
            : /gemeinsame Anwesenheit während einer bestimmten Maschinenschicht/,
        ),
      ).toBeVisible()
    },
  )

  it('keeps a calendar supply loss visible without inventing an over-allocation', async () => {
    vi.mocked(getWorkPackageReadiness).mockResolvedValue(
      evidence({
        personnel_status: 'not_fully_assessable',
        supply_gaps: [{ resource_id: 'person', resource_name: 'Ada', day: '2099-01-06' }],
      }),
    )
    setup()
    expect(await screen.findByText('Ada')).toBeVisible()
    expect(screen.getByText(/No personal calendar capacity/)).toBeVisible()
    expect(
      screen.queryByText('Assigned capacity exceeds available capacity'),
    ).not.toBeInTheDocument()
  })

  it('links a live machine blocker to all bookings of that resource, including other packages', async () => {
    vi.mocked(getWorkPackageReadiness).mockResolvedValue(
      evidence({
        status: 'conflicting',
        infrastructure_status: 'conflicting',
        conflicts: [
          {
            resource_id: 'crane',
            resource_name: 'Crane 1',
            resource_type: 'infrastructure',
            cause: 'booking_overlap',
            start_date: '2099-01-05',
            end_date: '2099-01-06',
            assignment_ids: ['own', 'competing'],
            total_assigned_percent: 200,
            available_percent: 100,
          },
        ],
      }),
    )
    const { onAssignments } = setup()
    expect(await screen.findByText('Exclusive equipment bookings overlap')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Review all resource bookings' }))
    expect(onAssignments).toHaveBeenCalledWith({ resourceId: 'crane' })
  })

  it('does not display a cached positive verdict while a new check is running', async () => {
    const client = createTestQueryClient()
    client.setQueryData(queryKeys.planning.readiness('wp'), evidence())
    let finish!: (data: Readiness) => void
    vi.mocked(getWorkPackageReadiness).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve
      }),
    )
    setup({ client })
    expect(await screen.findByText('Checking current inputs…')).toBeVisible()
    expect(screen.queryByText('Covered within scope')).not.toBeInTheDocument()
    await act(async () => finish(evidence()))
    expect(await screen.findByTestId('work-package-readiness')).toBeVisible()
  })

  it('replaces old positive evidence with an error after failed refresh and permits retry', async () => {
    const client = createTestQueryClient()
    client.setQueryData(queryKeys.planning.readiness('wp'), evidence())
    vi.mocked(getWorkPackageReadiness)
      .mockRejectedValueOnce(new Error('unavailable'))
      .mockResolvedValue(evidence())
    setup({ client })
    expect(
      await screen.findByText(
        'The current check failed. Previous positive results do not confirm the current plan.',
      ),
    ).toBeVisible()
    expect(screen.queryByTestId('work-package-readiness')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByTestId('work-package-readiness')).toBeVisible()
  })

  it('does not describe a failed overview load as covered requirements or no conflicts', async () => {
    vi.mocked(getPlanningOverview).mockRejectedValue(new Error('unavailable'))
    const client = createTestQueryClient()
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <MantineProvider>
            <I18nProvider locale="en">
              <PlanningOverviewPanel />
            </I18nProvider>
          </MantineProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByText('Readiness could not be assessed')).toBeVisible()
    await waitFor(() => expect(getPlanningOverview).toHaveBeenCalledTimes(1))
    expect(screen.queryByText('All work package requirements are covered.')).not.toBeInTheDocument()
    expect(screen.queryByText('No problems detected.')).not.toBeInTheDocument()
  })
  it('preserves existing work-package/resource conflict links from the Gantt chart', async () => {
    vi.mocked(getPlanningOverview).mockResolvedValue({
      work_packages: [wp],
      unmet_requirements: [],
      conflicts: [],
      mismatched_assignments: [],
    })
    const client = createTestQueryClient()
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/planning?work_package=wp&resource=crane']}>
          <MantineProvider>
            <I18nProvider locale="en">
              <PlanningOverviewPanel />
            </I18nProvider>
          </MantineProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByRole('button', { name: 'Show all conflicts' })).toBeVisible()
    expect(getWorkPackageReadiness).not.toHaveBeenCalled()
  })
})
