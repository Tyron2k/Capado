/**
 * A CUSTOMER'S NAME IS DISPLAYED WHERE IT IS NOT EDITED, and that is what these tests pin.
 *
 * Project lists and the folder tree show it, and both customer pickers offer it. So a write here
 * invalidates `customers` (covering BOTH list variants — the picker's active-only and this panel's
 * include-inactive) and `projects` (covering the rows that display the name).
 *
 * It does NOT invalidate the digest, and that absence is asserted: a customer is not a finding, and its
 * name changes nothing about the plan. This is the master-data side of the boundary the projects batch
 * drew, and the cheap mistake is to widen it "to be safe".
 *
 * A 409 is treated as a distinct outcome rather than a failure — "that name is taken" is information,
 * and the right response is to pick the existing customer rather than retry with a variant spelling.
 * That branch is tested because it is the one a reader would assume is just an error path.
 */
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../../api/customers', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../api/customers')>()),
  getCustomers: vi.fn(),
  createCustomer: vi.fn(),
  updateCustomer: vi.fn(),
  deleteCustomer: vi.fn(),
}))

const showErrorNotification = vi.fn()
vi.mock('../../../utils/errorHandling', () => ({
  showErrorNotification: (...args: unknown[]) => showErrorNotification(...args),
}))

const notificationsShow = vi.fn()
// Lazy, not `{ show: notificationsShow }`: a `vi.mock` factory is hoisted above the const, so reading
// the variable eagerly throws "cannot access before initialization". The arrow defers the read.
vi.mock('@mantine/notifications', () => ({
  notifications: { show: (...args: unknown[]) => notificationsShow(...args) },
}))

import {
  createCustomer,
  deleteCustomer,
  getCustomers,
  updateCustomer,
  type Customer,
} from '../../../api/customers'
import { queryKeys } from '../../../api/queryClient'
import { createTestQueryClient, trackInvalidations } from '../../../testUtils/queryClient'
import { I18nProvider } from '../../../i18n'
import { CustomerPanel } from './CustomerPanel'

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
  // Mantine's Modal subscribes to the visual viewport for its scroll lock, and jsdom has none. The
  // repo's other tests avoid this by mocking the form component away; this panel renders its form
  // inline, so the shim is the smaller of the two evils.
  Object.defineProperty(window, 'visualViewport', {
    writable: true,
    value: { addEventListener: vi.fn(), removeEventListener: vi.fn(), height: 768, width: 1024 },
  })
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  window.confirm = vi.fn(() => true)
})

const customer: Customer = {
  id: 'c1',
  name: 'Werke Nord GmbH',
  reference: 'WN',
  note: '',
  is_active: true,
  folder_count: 0,
  project_count: 2,
} as unknown as Customer

function renderPanel() {
  const client = createTestQueryClient()
  const invalidated = trackInvalidations(client)
  const view = render(
    <QueryClientProvider client={client}>
      <MantineProvider env="test">
        <I18nProvider locale="de">
          <CustomerPanel />
        </I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
  return { ...view, invalidated }
}

/** The plan-shaped keys a customer write must leave alone. */
const PLAN_KEYS = [
  queryKeys.digest.all,
  queryKeys.assignments.all,
  queryKeys.conflicts.all,
  queryKeys.planning.all,
  queryKeys.capacity.all,
]

beforeEach(() => {
  vi.mocked(getCustomers).mockResolvedValue([customer])
  vi.mocked(createCustomer).mockReset()
  vi.mocked(updateCustomer).mockReset()
  vi.mocked(deleteCustomer).mockReset()
  showErrorNotification.mockReset()
  notificationsShow.mockReset()
})

describe('retiring a customer', () => {
  it('invalidates customers and the projects that display the name, and nothing else', async () => {
    vi.mocked(updateCustomer).mockResolvedValue(customer)

    const { invalidated } = renderPanel()
    await waitFor(() => expect(screen.getByTestId('customer-retire-c1')).toBeTruthy())
    fireEvent.click(screen.getByTestId('customer-retire-c1'))

    await waitFor(() => expect(updateCustomer).toHaveBeenCalledWith('c1', { is_active: false }))
    await waitFor(() => {
      expect(invalidated).toContainEqual([...queryKeys.customers.all])
      expect(invalidated).toContainEqual([...queryKeys.projects.all])
    })

    // A customer is not a finding. If this list grows, somebody widened the invalidation without a
    // reason -- the mistake this boundary exists to prevent.
    for (const key of PLAN_KEYS) {
      expect(invalidated).not.toContainEqual([...key])
    }
  })

  it('invalidates nothing when the write fails', async () => {
    vi.mocked(updateCustomer).mockRejectedValue(new Error('boom'))

    const { invalidated } = renderPanel()
    await waitFor(() => expect(screen.getByTestId('customer-retire-c1')).toBeTruthy())
    fireEvent.click(screen.getByTestId('customer-retire-c1'))

    await waitFor(() => expect(showErrorNotification).toHaveBeenCalledTimes(1))
    expect(invalidated).toEqual([])
  })
})

describe('deleting a customer', () => {
  it('invalidates after a successful delete', async () => {
    vi.mocked(deleteCustomer).mockResolvedValue(undefined)

    const { invalidated } = renderPanel()
    await waitFor(() => expect(screen.getByTestId('customer-delete-c1')).toBeTruthy())
    fireEvent.click(screen.getByTestId('customer-delete-c1'))

    await waitFor(() => expect(deleteCustomer).toHaveBeenCalledWith('c1'))
    await waitFor(() => expect(invalidated).toContainEqual([...queryKeys.customers.all]))
  })

  it('does not write when the confirmation is declined', async () => {
    vi.mocked(window.confirm).mockReturnValueOnce(false)

    const { invalidated } = renderPanel()
    await waitFor(() => expect(screen.getByTestId('customer-delete-c1')).toBeTruthy())
    fireEvent.click(screen.getByTestId('customer-delete-c1'))

    expect(deleteCustomer).not.toHaveBeenCalled()
    expect(invalidated).toEqual([])
  })

  it('reports a failed delete without invalidating', async () => {
    vi.mocked(deleteCustomer).mockRejectedValue(new Error('boom'))

    const { invalidated } = renderPanel()
    await waitFor(() => expect(screen.getByTestId('customer-delete-c1')).toBeTruthy())
    fireEvent.click(screen.getByTestId('customer-delete-c1'))

    await waitFor(() => expect(showErrorNotification).toHaveBeenCalledTimes(1))
    expect(invalidated).toEqual([])
  })
})

/**
 * NO TESTS FOR THE SAVE PATH HERE, and that is a limitation rather than an oversight.
 *
 * The draft form lives inside a Mantine `Modal`, which does not render under jsdom in this project:
 * it subscribes to browser APIs jsdom lacks, and shimming them was tried and did not get there. Every
 * other test in this repo works around it the same way — by mocking the form component out entirely
 * (see AssignmentsPanel.test.tsx and WorkPackagesSection.test.tsx) — which is not available here,
 * because this panel renders its form inline rather than as a separate component.
 *
 * What that leaves untested is the 409 branch: a duplicate name is reported as an orange notice rather
 * than through the generic error path, because "that name is taken" is information and the right
 * response is to pick the existing customer instead of retrying with a variant spelling. It is
 * commented in CustomerPanel.tsx; it is not pinned.
 */

describe('reading the customer list', () => {
  it('reports a failed load', async () => {
    vi.mocked(getCustomers).mockRejectedValue(new Error('boom'))

    renderPanel()
    await waitFor(() => expect(showErrorNotification).toHaveBeenCalledTimes(1))
  })
})
