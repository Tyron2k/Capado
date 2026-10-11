// @vitest-environment jsdom
import { beforeAll, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { render, screen, within } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { I18nProvider } from '../../i18n'
import { DashboardStats } from './DashboardStats'
import type { DashboardResponse } from '../../types/dashboard'
import type { ProjectOverviewItem } from '../../api/projectOverview'

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((media: string) => ({
      matches: false,
      media,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  })
})
const week = {
  week_start: '2026-10-05',
  total_available: 100,
  total_assigned: 72.4,
  utilization: 72.4,
  overbooked: 0,
  color: 'green',
}
const dashboard: DashboardResponse = {
  personal_utilization: [week],
  infrastructure_utilization: [],
  projects: [],
}
const project: ProjectOverviewItem = {
  project_id: 'fictional-project',
  project_name: 'Test project',
  start_date: '2026-10-05',
  end_date: '2026-10-09',
  next_deadline: '2026-10-09',
  active_work_package_count: 3,
  average_resource_utilization_percent: null,
  progress_percent: 0,
  open_conflict_count: 0,
  commitment_breach: null,
  critical_work_package_count: 0,
  late_work_packages: [],
  dependency_violations: [],
  min_float_working_days: null,
}
function show(
  data: DashboardResponse | null,
  projects: ProjectOverviewItem[] = [],
  failed = false,
  locale: 'en' | 'de' = 'en',
) {
  return render(
    <MantineProvider>
      <I18nProvider locale={locale}>
        <DashboardStats
          dashboard={data}
          projects={projects}
          dashboardPending={false}
          projectsPending={false}
          projectsFailed={failed}
        />
      </I18nProvider>
    </MantineProvider>,
  )
}
describe('DashboardStats', () => {
  it('reports actual returned counts and utilization, labelled with their week', () => {
    show(dashboard, [project, { ...project, project_id: 'second', active_work_package_count: 2 }])
    expect(within(screen.getByRole('region', { name: 'Projects' })).getByText('2')).toBeVisible()
    expect(
      within(screen.getByRole('region', { name: 'Active work packages' })).getByText('5'),
    ).toBeVisible()
    const people = within(screen.getByRole('region', { name: 'People Utilization' }))
    expect(people.getByText('72.4 %')).toBeVisible()
    expect(people.getByText('CW 41')).toBeVisible()
  })
  it('distinguishes a successful empty result from unavailable data', () => {
    show(null)
    expect(within(screen.getByRole('region', { name: 'Projects' })).getByText('0')).toBeVisible()
    expect(
      within(screen.getByRole('region', { name: 'People Utilization' })).getByText('—'),
    ).toBeVisible()
    expect(
      within(screen.getByRole('region', { name: 'Infrastructure Utilization' })).getByText(
        'Data unavailable',
      ),
    ).toBeVisible()
  })
  it('does not present a failed project request as zero projects', () => {
    show(null, [], true)
    const projects = within(screen.getByRole('region', { name: 'Projects' }))
    expect(projects.getByText('—')).toBeVisible()
    expect(projects.queryByText('0')).toBeNull()
  })
  it('does not interpret zero capacity as a measured zero utilization', () => {
    show({ ...dashboard, personal_utilization: [{ ...week, utilization: 0, total_available: 0 }] })
    expect(
      within(screen.getByRole('region', { name: 'People Utilization' })).getByText('—'),
    ).toBeVisible()
  })
  it('formats the existing utilization for German readers', () => {
    show(dashboard, [], false, 'de')
    expect(screen.getByText('72,4 %')).toBeVisible()
    expect(screen.getByText('KW 41')).toBeVisible()
  })
})
