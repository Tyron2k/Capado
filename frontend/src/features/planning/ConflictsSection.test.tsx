// @vitest-environment jsdom

import { beforeAll, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import type { Assignment, Conflict } from '../../types/assignment'
import { I18nProvider } from '../../i18n'
import { ConflictsSection } from './ConflictsSection'

vi.mock('../conflicts/ProblemCard', () => ({
  ProblemCard: ({
    bucket,
    initiallyOpen,
    focusedWorkPackageId,
  }: {
    bucket: { resource_name: string; type: string }
    initiallyOpen: boolean
    focusedWorkPackageId?: string
  }) => (
    <div
      data-testid={`problem-${bucket.type}-${bucket.resource_name}`}
      data-open={initiallyOpen}
      data-focused-package={focusedWorkPackageId}
    />
  ),
}))

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
})

const conflicts: Conflict[] = [
  {
    id: 'c1',
    resource_id: 'anna',
    resource_name: 'Anna Berger',
    resource_type: 'personal',
    start_date: '2026-10-05',
    end_date: '2026-10-23',
    total_assigned_percent: 120,
    available_percent: 100,
    severity: 'medium',
    overload_ratio: 1.2,
    detected_at: '2026-09-25T00:00:00Z',
    assignments: [
      {
        assignment_id: 'a1',
        project_id: 'p1',
        project_name: 'Project One',
        work_package_id: 'painting',
        work_package_name: 'Lackierung',
      },
      { assignment_id: 'a2', project_id: 'p2', work_package_id: 'coating' },
    ],
  },
  {
    id: 'c2',
    resource_id: 'bernd',
    resource_name: 'Bernd Kluge',
    resource_type: 'personal',
    start_date: '2026-10-05',
    end_date: '2026-10-06',
    total_assigned_percent: 130,
    available_percent: 100,
    severity: 'high',
    overload_ratio: 1.3,
    detected_at: '2026-09-25T00:00:00Z',
    assignments: [{ assignment_id: 'a3', project_id: 'p2', work_package_id: 'welding' }],
  },
]

function renderSection(focus: { projectId?: string; workPackageId?: string } | null) {
  const onClearFocus = vi.fn()
  render(
    <MantineProvider env="test">
      <I18nProvider locale="de">
        <ConflictsSection
          conflicts={conflicts}
          mismatches={[] as Assignment[]}
          onChanged={vi.fn()}
          focus={focus}
          onClearFocus={onClearFocus}
        />
      </I18nProvider>
    </MantineProvider>,
  )
  return onClearFocus
}

describe('focused planning conflicts', () => {
  it('shows only the affected resource, opens it, and names the work package', () => {
    const onClearFocus = renderSection({ workPackageId: 'painting' })

    expect(screen.getByText('Konflikte aus dem Gantt: Lackierung')).toBeInTheDocument()
    expect(screen.getByTestId('problem-capacity-Anna Berger')).toHaveAttribute('data-open', 'true')
    expect(screen.getByTestId('problem-capacity-Anna Berger')).toHaveAttribute(
      'data-focused-package',
      'painting',
    )
    expect(screen.queryByTestId('problem-capacity-Bernd Kluge')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Alle Konflikte anzeigen' }))
    expect(onClearFocus).toHaveBeenCalledOnce()
  })

  it('explains when a linked conflict has already disappeared', () => {
    renderSection({ workPackageId: 'resolved' })

    expect(
      screen.getByText('Für diese Auswahl liegen keine aktuellen Konflikte vor.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Alle Konflikte anzeigen' })).toBeInTheDocument()
  })

  it('shows all resources affected by a project badge', () => {
    renderSection({ projectId: 'p2' })

    expect(screen.getByTestId('problem-capacity-Anna Berger')).toBeInTheDocument()
    expect(screen.getByTestId('problem-capacity-Bernd Kluge')).toBeInTheDocument()
  })
})
