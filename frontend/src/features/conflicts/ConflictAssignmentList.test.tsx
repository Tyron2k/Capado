// @vitest-environment jsdom

import { beforeAll, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { MemoryRouter } from 'react-router-dom'
import { I18nProvider } from '../../i18n'
import { ConflictAssignmentList } from './ConflictAssignmentList'

vi.mock('../../hooks/usePermissions', () => ({
  usePermissions: () => ({ canWrite: false }),
}))
vi.mock('./ConflictResolutionActions', () => ({ ConflictResolutionActions: () => null }))

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

describe('focused conflict assignment', () => {
  it('highlights only the selected work package within a shared conflict', () => {
    render(
      <MemoryRouter>
        <MantineProvider env="test">
          <I18nProvider locale="de">
            <ConflictAssignmentList
              assignments={[
                {
                  assignment_id: 'a1',
                  project_id: 'p1',
                  project_name: 'Project One',
                  work_package_id: 'painting',
                  work_package_name: 'Lackierung',
                  start_date: '2026-10-05',
                  end_date: '2026-10-23',
                },
                {
                  assignment_id: 'a2',
                  project_id: 'p1',
                  project_name: 'Project One',
                  work_package_id: 'coating',
                  work_package_name: 'Pulverbeschichtung',
                  start_date: '2026-10-05',
                  end_date: '2026-10-23',
                },
              ]}
              focusedWorkPackageId="painting"
              onChanged={vi.fn()}
            />
          </I18nProvider>
        </MantineProvider>
      </MemoryRouter>,
    )

    expect(screen.getByText('Lackierung').closest('tr')).toHaveAttribute('data-focused', 'true')
    expect(screen.getByText('Pulverbeschichtung').closest('tr')).not.toHaveAttribute('data-focused')
  })
})
