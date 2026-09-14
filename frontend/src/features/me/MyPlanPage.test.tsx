/**
 * The three states of the self-service page.
 *
 * The one that matters is the middle one: an account nobody has linked yet must NOT render as an
 * empty plan. "Nothing scheduled" and "nobody told this system who you are" are different answers,
 * and showing the first for the second would have a person conclude they have no work.
 */

import type { ReactNode } from 'react'
import '@testing-library/jest-dom/vitest'
import { MantineProvider } from '@mantine/core'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

// Mantine reads matchMedia, which jsdom does not implement. Same stub the other page tests use.
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
})

const getMyPlan = vi.fn()

vi.mock('../../api/me', async () => {
  const actual = await vi.importActual<typeof import('../../api/me')>('../../api/me')
  return { ...actual, getMyPlan: () => getMyPlan() }
})

// A STABLE t, deliberately. The real useTranslation memoises it (useCallback + useMemo on the
// context value), and the page depends on it inside a useCallback. A mock that returns a fresh
// function on every render would make the load effect re-fire forever — a loop in the test that
// does not exist in the application.
const stableT = (key: string) => key
vi.mock('../../i18n', () => ({
  useTranslation: () => ({ t: stableT }),
}))

import { NoLinkedResourceError } from '../../api/me'
import { QueryClientProvider } from '@tanstack/react-query'

import { createTestQueryClient } from '../../testUtils/queryClient'
import { MyPlanPage } from './MyPlanPage'

function renderWithProviders(ui: ReactNode) {
  // A fresh client per render: a shared one would carry one test's cached plan into the next.
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MantineProvider>{ui}</MantineProvider>
    </QueryClientProvider>,
  )
}

const emptyPlan = {
  resource_id: 'r-1',
  assignments: [],
  assignment_total: 0,
  absences: [],
  absence_total: 0,
  skills: [],
}

describe('MyPlanPage', () => {
  beforeEach(() => {
    getMyPlan.mockReset()
  })

  it('shows the not-linked message instead of an empty plan', async () => {
    getMyPlan.mockRejectedValue(new NoLinkedResourceError())

    renderWithProviders(<MyPlanPage />)

    await waitFor(() => {
      expect(screen.getByText('myPlan.notLinkedTitle')).toBeInTheDocument()
    })
    // The distinction the whole state exists for: no empty-plan wording anywhere.
    expect(screen.queryByText('myPlan.noAssignments')).not.toBeInTheDocument()
  })

  it('renders an empty plan as an empty plan', async () => {
    getMyPlan.mockResolvedValue(emptyPlan)

    renderWithProviders(<MyPlanPage />)

    await waitFor(() => {
      expect(screen.getByText('myPlan.noAssignments')).toBeInTheDocument()
    })
    expect(screen.queryByText('myPlan.notLinkedTitle')).not.toBeInTheDocument()
  })

  it('renders assignments, absences and qualifications when there are some', async () => {
    getMyPlan.mockResolvedValue({
      ...emptyPlan,
      assignments: [
        {
          id: 'a-1',
          resource_id: 'r-1',
          resource_type: 'personal',
          work_package_id: 'wp-1',
          work_package_name: 'Assembly',
          project_name: 'Order 4711',
          start_date: '2026-09-07',
          end_date: '2026-09-11',
          allocation_percent: 50,
          start_at: null,
          end_at: null,
          skill_mismatch: false,
          created_at: '2026-09-01T00:00:00',
          updated_at: '2026-09-01T00:00:00',
        },
      ],
      assignment_total: 1,
      skills: [
        {
          id: 's-1',
          skill_attribute_id: 'sa-1',
          skill_id: 'sk-1',
          skill_name: 'Welding',
          attribute_name: 'Type Alpha',
          valid_from: null,
          valid_until: null,
          level: null,
        },
      ],
    })

    renderWithProviders(<MyPlanPage />)

    await waitFor(() => {
      expect(screen.getByText('Order 4711')).toBeInTheDocument()
    })
    expect(screen.getByText('Welding')).toBeInTheDocument()
    // A null level reads as "not assessed", which is not the same as 1.
    expect(screen.getByText('myPlan.levelUnassessed')).toBeInTheDocument()
    expect(screen.getByText('myPlan.noExpiry')).toBeInTheDocument()
  })

  it('shows an error when the request fails for any other reason', async () => {
    getMyPlan.mockRejectedValue(new Error('boom'))

    renderWithProviders(<MyPlanPage />)

    await waitFor(() => {
      expect(screen.getByText('myPlan.loadFailed')).toBeInTheDocument()
    })
  })
})
