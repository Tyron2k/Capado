import '@testing-library/jest-dom/vitest'
import { MantineProvider } from '@mantine/core'
import { render, screen, within } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { I18nProvider, type Locale } from '../../i18n'
import type { Assignment, AssignmentCreate, AssignmentPreview } from '../../types/assignment'
import { AssignmentChangeSummary } from './AssignmentChangeSummary'

vi.mock('../../context/SettingsContext', () => ({
  useSettings: () => ({ settings: { timeZone: 'Europe/Berlin' } }),
}))

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  })
})

const before: Assignment = {
  id: 'a1',
  resource_id: 'crane',
  resource_name: 'Crane',
  resource_type: 'infrastructure',
  work_package_id: 'wp',
  work_package_name: 'Assembly',
  project_id: 'p',
  project_name: 'Order A',
  start_at: '2099-01-07T20:00:00Z',
  end_at: '2099-01-08T00:00:00Z',
  start_date: null,
  end_date: null,
  allocation_percent: null,
  skill_mismatch: false,
  created_at: '2026-11-04T08:00:00Z',
  updated_at: '2026-11-04T08:00:00Z',
}
const preview: AssignmentPreview = {
  resources: [
    {
      resource_id: 'crane',
      resource_name: 'Crane',
      resource_type: 'infrastructure',
      conflicts_before: [],
      conflicts_after: [],
      capacity_days: [],
    },
  ],
}
const after: AssignmentCreate = {
  resource_id: 'crane',
  resource_type: 'infrastructure',
  work_package_id: 'wp',
  start_at: '2099-01-06T01:00:00Z',
  end_at: '2099-01-06T05:00:00Z',
}

function show(locale: Locale, proposed = after, original = before) {
  render(
    <MantineProvider>
      <I18nProvider locale={locale}>
        <AssignmentChangeSummary before={original} after={proposed} preview={preview} />
      </I18nProvider>
    </MantineProvider>,
  )
  return screen.getByRole('table', {
    name: locale === 'de' ? 'Geplante Änderung' : 'Proposed change',
  })
}

describe('concrete assignment changes', () => {
  it.each(['de', 'en'] as const)(
    'shows both ends of an overnight move and preserved duration in %s',
    (locale) => {
      const table = show(locale)
      const start = within(table).getByRole('row', {
        name: locale === 'de' ? /Belegt von/ : /Occupied From/,
      })
      const end = within(table).getByRole('row', {
        name: locale === 'de' ? /Belegt bis/ : /Occupied Until/,
      })
      expect(start).toHaveTextContent(
        locale === 'de' ? '07.01.2099 21:00:00 (UTC+01:00)' : '2099-01-07 21:00:00 (UTC+01:00)',
      )
      expect(start).toHaveTextContent(
        locale === 'de' ? '06.01.2099 02:00:00 (UTC+01:00)' : '2099-01-06 02:00:00 (UTC+01:00)',
      )
      expect(end).toHaveTextContent(
        locale === 'de' ? '08.01.2099 01:00:00 (UTC+01:00)' : '2099-01-08 01:00:00 (UTC+01:00)',
      )
      expect(end).toHaveTextContent(
        locale === 'de' ? '06.01.2099 06:00:00 (UTC+01:00)' : '2099-01-06 06:00:00 (UTC+01:00)',
      )
      const duration = within(table).getByRole('row', {
        name: locale === 'de' ? /Dauer/ : /Duration/,
      })
      expect(within(duration).getAllByText('240 min')).toHaveLength(2)
      expect(duration).toHaveTextContent(locale === 'de' ? 'Unverändert' : 'Unchanged')
      expect(screen.getByText(/Europe\/Berlin/)).toBeVisible()
      expect(screen.getByText(/Assembly/)).toBeVisible()
      expect(screen.getByText(/Order A/)).toBeVisible()
    },
  )

  it('distinguishes the repeated autumn hour by offset and elapsed duration', () => {
    const table = show(
      'en',
      {
        ...after,
        start_at: '2026-10-25T01:15:00Z',
        end_at: '2026-10-25T02:15:00Z',
      },
      { ...before, start_at: '2026-10-25T00:15:00Z', end_at: '2026-10-25T02:15:00Z' },
    )
    const start = within(table).getByRole('row', { name: /Occupied From/ })
    expect(start).toHaveTextContent('2026-10-25 02:15:00 (UTC+02:00)')
    expect(start).toHaveTextContent('2026-10-25 02:15:00 (UTC+01:00)')
    expect(start).toHaveTextContent('Changed')
    const duration = within(table).getByRole('row', { name: /Duration/ })
    expect(duration).toHaveTextContent('120 min')
    expect(duration).toHaveTextContent('60 min')
  })
})
