/**
 * Groups on the query layer: the same cross-screen invalidation as sites, one key further.
 *
 * `group_name` is denormalised onto every resource response exactly as `site_name` is, so renaming or
 * deleting a group changes what the people and infrastructure tables display. The hand-written version
 * reloaded this panel only.
 *
 * What is worth pinning here is the pair of decisions, not that the list refreshes:
 *
 * 1. The resources key IS invalidated — a group's name is on those lists.
 * 2. The digest key is NOT — a group is an organisational label, and no finding is derived from what a
 *    group is called. That absence is a decision, and a test is the only place it stays one; without it
 *    somebody adds the invalidation later "to be safe" and every group rename refetches the dashboard.
 */
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../../api/resources', () => ({
  getGroups: vi.fn(),
  createGroup: vi.fn(),
  updateGroup: vi.fn(),
  deleteGroup: vi.fn(),
}))

const showErrorNotification = vi.fn()
vi.mock('../../../utils/errorHandling', () => ({
  showErrorNotification: (...args: unknown[]) => showErrorNotification(...args),
}))

vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}))

import { createGroup, deleteGroup, getGroups, updateGroup } from '../../../api/resources'
import type { ResourceGroup } from '../../../types/resource'
import { queryKeys } from '../../../api/queryClient'
import { createTestQueryClient, trackInvalidations } from '../../../testUtils/queryClient'
import { I18nProvider } from '../../../i18n'
import { GroupsPanel } from './GroupsPanel'

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
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

function group(id: string, name: string): ResourceGroup {
  return { id, name, resource_type: 'personal', parent_id: null } as ResourceGroup
}

function renderPanel() {
  const client = createTestQueryClient()
  const invalidated = trackInvalidations(client)
  const view = render(
    <QueryClientProvider client={client}>
      <MantineProvider>
        <I18nProvider locale="de">
          <GroupsPanel resourceType="personal" />
        </I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
  return { ...view, invalidated }
}

describe('GroupsPanel on the query layer', () => {
  beforeEach(() => {
    vi.mocked(getGroups).mockReset()
    vi.mocked(createGroup).mockReset()
    vi.mocked(updateGroup).mockReset()
    vi.mocked(deleteGroup).mockReset()
    showErrorNotification.mockReset()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('renders the groups the endpoint returned', async () => {
    vi.mocked(getGroups).mockResolvedValue([group('g1', 'Lackierer')])

    renderPanel()

    await waitFor(() => expect(screen.getByText('Lackierer')).toBeTruthy())
  })

  it('keys the list by resource type, so people and machines do not share an entry', async () => {
    // Two panels, two resource types, one cache. Without the type in the key the second panel would
    // render the first one's groups — and both lists are plausible, so nobody would notice quickly.
    vi.mocked(getGroups).mockResolvedValue([group('g1', 'Lackierer')])

    renderPanel()

    await waitFor(() => expect(getGroups).toHaveBeenCalledWith('personal'))
    expect(queryKeys.resources.groups('personal')).not.toEqual(
      queryKeys.resources.groups('infrastructure'),
    )
  })

  it('invalidates the resource lists when a group is deleted', async () => {
    vi.mocked(getGroups).mockResolvedValue([group('g1', 'Lackierer')])
    vi.mocked(deleteGroup).mockResolvedValue(undefined)

    const { invalidated } = renderPanel()
    await waitFor(() => expect(screen.getByText('Lackierer')).toBeTruthy())

    fireEvent.click(screen.getByTestId('group-delete-g1'))

    await waitFor(() => expect(deleteGroup).toHaveBeenCalledWith('g1'))
    await waitFor(() => expect(invalidated).toContainEqual([...queryKeys.resources.all]))
  })

  it('does not invalidate the digest, because a group name is not a finding', async () => {
    // A decision, asserted so it stays one. The digest is derived from qualifications, commitments,
    // dependencies and requirements — none of which reference what a group is called. Invalidating it
    // here would refetch the dashboard on every rename for nothing.
    vi.mocked(getGroups).mockResolvedValue([group('g1', 'Lackierer')])
    vi.mocked(deleteGroup).mockResolvedValue(undefined)

    const { invalidated } = renderPanel()
    await waitFor(() => expect(screen.getByText('Lackierer')).toBeTruthy())
    fireEvent.click(screen.getByTestId('group-delete-g1'))

    await waitFor(() => expect(deleteGroup).toHaveBeenCalled())
    expect(invalidated).not.toContainEqual([...queryKeys.digest.all])
  })

  it('invalidates nothing when the delete fails', async () => {
    vi.mocked(getGroups).mockResolvedValue([group('g1', 'Lackierer')])
    vi.mocked(deleteGroup).mockRejectedValue(new Error('boom'))

    const { invalidated } = renderPanel()
    await waitFor(() => expect(screen.getByText('Lackierer')).toBeTruthy())
    fireEvent.click(screen.getByTestId('group-delete-g1'))

    await waitFor(() => expect(showErrorNotification).toHaveBeenCalledTimes(1))
    expect(invalidated).toEqual([])
  })

  it('shows the load failure as a message on the panel, not as a notification', async () => {
    // This screen renders its own error state rather than notifying: it is one panel among several on
    // a tab, and a toast would not say which of them failed.
    vi.mocked(getGroups).mockRejectedValue(new Error('boom'))

    renderPanel()

    await waitFor(() => expect(screen.getByText(/nicht geladen|fehlgeschlagen/i)).toBeTruthy())
    expect(showErrorNotification).not.toHaveBeenCalled()
  })
})
