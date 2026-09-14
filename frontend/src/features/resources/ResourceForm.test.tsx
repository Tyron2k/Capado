/**
 * Tests for the site field on the resource form.
 *
 * The assertion that matters is the EMPTY one. Mantine's Select yields '' when cleared, and ''
 * spread into the payload would reach the API as an empty string rather than as null — so the
 * resource would keep its old site while the user watched the field go blank and the save succeed.
 * The form therefore maps '' to null, and that mapping is what is pinned here.
 *
 * Also pinned: the field is HIDDEN when the installation has no sites. A single-plant operator must
 * not be shown a control whose only possible value is empty.
 */

// @vitest-environment jsdom

import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'

import { createTestQueryClient } from '../../testUtils/queryClient'
import { I18nProvider } from '../../i18n'
import { ResourceForm } from './ResourceForm'
import { normalizeSiteId } from './utils/siteValue'

vi.mock('../../api/resources', () => ({
  getGroups: vi.fn(() =>
    Promise.resolve([{ id: 'g1', name: 'Lackierer', resource_type: 'personal' }]),
  ),
}))

vi.mock('../../api/calendar', () => ({
  listSites: vi.fn(() => Promise.resolve([])),
}))

import { listSites } from '../../api/calendar'

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
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

function renderForm(
  onSubmit: (v: unknown) => void,
  initialValues?: { name: string; group_id: string; site_id?: string | null } | null,
) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MantineProvider>
        <I18nProvider locale="de">
          <ResourceForm resourceType="personal" initialValues={initialValues} onSubmit={onSubmit} />
        </I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
}

describe('ResourceForm site field', () => {
  beforeEach(() => {
    vi.mocked(listSites).mockResolvedValue([
      { id: 's1', name: 'Werk Ammendorf', is_active: true },
      { id: 's2', name: 'Werk Leipzig', is_active: true },
    ] as never)
  })

  it('hides the site field when the installation has no sites', async () => {
    vi.mocked(listSites).mockResolvedValue([] as never)
    renderForm(vi.fn())
    await waitFor(() => expect(screen.getByRole('button')).toBeTruthy())
    expect(screen.queryByPlaceholderText('Betriebsstätte wählen (optional)')).toBeNull()
  })

  it('shows the site field when sites exist', async () => {
    renderForm(vi.fn())
    await waitFor(() =>
      expect(screen.getByPlaceholderText('Betriebsstätte wählen (optional)')).toBeTruthy(),
    )
  })

  it('submits null for the site when none is chosen', async () => {
    const onSubmit = vi.fn()
    renderForm(onSubmit, { name: 'Müller', group_id: 'g1' })
    await waitFor(() =>
      expect(screen.getByPlaceholderText('Betriebsstätte wählen (optional)')).toBeTruthy(),
    )

    fireEvent.click(screen.getByRole('button'))

    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    expect(onSubmit.mock.calls[0][0]).toMatchObject({ site_id: null })
  })

  it('keeps a pre-filled site when nothing is touched', async () => {
    const onSubmit = vi.fn()
    renderForm(onSubmit, { name: 'Müller', group_id: 'g1', site_id: 's2' })
    await waitFor(() =>
      expect(screen.getByPlaceholderText('Betriebsstätte wählen (optional)')).toBeTruthy(),
    )

    fireEvent.click(screen.getByRole('button'))

    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    expect(onSubmit.mock.calls[0][0]).toMatchObject({ site_id: 's2' })
  })
})

describe('normalizeSiteId', () => {
  it('turns a cleared Select into null', () => {
    // The case the rendering tests could NOT reach: a pre-filled Select yields '' when cleared,
    // and this test failed when the mapping was removed while the rendering tests still passed.
    expect(normalizeSiteId('')).toBeNull()
  })

  it('turns undefined into null', () => {
    expect(normalizeSiteId(undefined)).toBeNull()
  })

  it('passes null through', () => {
    expect(normalizeSiteId(null)).toBeNull()
  })

  it('leaves a chosen site untouched', () => {
    expect(normalizeSiteId('s2')).toBe('s2')
  })
})
