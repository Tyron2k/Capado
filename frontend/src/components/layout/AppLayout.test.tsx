/**
 * Navigation grouping tests.
 *
 * The regrouping into question-based blocks moved the admin check from a whole
 * LIST onto the individual ITEM, so a group can now mix admin and non-admin
 * entries. That is the risky part: a per-item flag is easy to forget on a new
 * entry, and the failure mode is a non-admin seeing a link to an admin page.
 * These tests pin the property, not the layout — reordering the groups or
 * renaming a heading must not fail them.
 */
import { MantineProvider } from '@mantine/core'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeAll, describe, expect, it, vi } from 'vitest'

import { AppLayout } from './AppLayout'
import { I18nProvider } from '../../i18n'

const mockIsAdmin = vi.fn(() => false)

vi.mock('../../hooks/usePermissions', () => ({
  usePermissions: () => ({ isAdmin: mockIsAdmin(), canWrite: false, canEditGroup: () => false }),
}))

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u1', email: 'v@example.com', full_name: 'Viewer', role: 'viewer' },
    logout: vi.fn(),
  }),
}))

vi.mock('../../context/SettingsContext', () => ({
  useSettings: () => ({
    settings: { companyName: 'Test', companySubtitle: '', primaryColor: '#1c7ed6' },
    updatePreferences: vi.fn(),
    hasUploadedLogo: false,
  }),
}))

beforeAll(() => {
  // The navbar's link list sits in a Mantine ScrollArea, which measures itself. jsdom has no
  // ResizeObserver, and without this stub every test in this file fails on the layout rather than on
  // anything it is asserting.
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver

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

/**
 * Pages reachable only by an administrator.
 *
 * Wrapped in I18nProvider below, so these are the real German labels. Two
 * earlier drafts of this file were green while proving nothing: the first
 * asserted German labels with no provider, so `t()` returned the raw KEY and
 * "Planstände" was absent because nothing was translated — not because the
 * permission check worked. The differential admin test is what exposed it.
 */
const ADMIN_LABELS = ['Planstände', 'Arbeitszeit', 'Einstellungen', 'Benutzerverwaltung']

function renderShell() {
  return render(
    <MantineProvider>
      <I18nProvider locale="de">
        <MemoryRouter initialEntries={['/']}>
          <AppLayout />
        </MemoryRouter>
      </I18nProvider>
    </MantineProvider>,
  )
}

describe('AppLayout navigation', () => {
  it('hides every admin-gated entry from a non-admin', () => {
    mockIsAdmin.mockReturnValue(false)
    renderShell()

    for (const label of ADMIN_LABELS) {
      expect(screen.queryByText(label)).toBeNull()
    }
  })

  it('shows every admin-gated entry to an admin', () => {
    // The differential half: without this, the test above would also pass if the
    // labels were simply never rendered at all — which is exactly how two earlier
    // drafts of this file passed while proving nothing.
    mockIsAdmin.mockReturnValue(true)
    renderShell()

    for (const label of ADMIN_LABELS) {
      expect(screen.getByText(label)).toBeTruthy()
    }
  })

  it('does not leave a group heading behind when all its entries are hidden', () => {
    mockIsAdmin.mockReturnValue(false)
    renderShell()

    // "Verwaltung" holds only admin entries, so a viewer must not see the heading
    // either: an empty labelled block reads as a broken page rather than a hidden one.
    expect(screen.queryByText('Verwaltung')).toBeNull()
  })

  it('shows a mixed group to a non-admin without its admin entry', () => {
    mockIsAdmin.mockReturnValue(false)
    renderShell()

    // "Pflegen" mixes both: people/infrastructure/projects for everyone, working time
    // for admins only. The heading and the open entries must survive; the gated one must not.
    expect(screen.getByText('Pflegen')).toBeTruthy()
    expect(screen.getByText('Personen')).toBeTruthy()
    expect(screen.queryByText('Arbeitszeit')).toBeNull()
  })

  it('groups the everyday entries under question headings', () => {
    mockIsAdmin.mockReturnValue(false)
    renderShell()

    expect(screen.getByText('Planen')).toBeTruthy()
    expect(screen.getByText('Pflegen')).toBeTruthy()
  })
})
