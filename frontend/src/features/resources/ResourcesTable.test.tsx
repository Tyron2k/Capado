// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { I18nProvider } from '../../i18n'
import type { FlatResource } from './utils/resourceTableUtils'
import { ResourcesTable } from './ResourcesTable'

beforeAll(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  )
  Element.prototype.scrollIntoView = vi.fn()
})
afterEach(cleanup)
const resources = [
  {
    id: '1',
    name: 'Zebra',
    group_id: 'g1',
    group_name: 'Assembly',
    site_name: 'Plant A',
    conflict_count: 0,
  },
  {
    id: '2',
    name: 'Alpha',
    group_id: 'g2',
    group_name: 'Assembly',
    site_name: 'Plant B',
    conflict_count: 2,
  },
  {
    id: '3',
    name: 'Beta',
    group_id: 'g2',
    group_name: 'Assembly',
    site_name: '',
    conflict_count: 1,
  },
]
const props = () => ({
  resources,
  loading: false,
  hasSites: true,
  searchLabel: 'Find people',
  emptyLabel: 'No people',
  createLabel: 'New person',
  canWrite: true,
  onCreate: vi.fn(),
  onConflicts: vi.fn(),
  renderActions: (resource: FlatResource) => <button>{resource.name} skills</button>,
  testId: 'people',
})
const view = (values: ReturnType<typeof props>) => (
  <MantineProvider>
    <I18nProvider locale="en">
      <ResourcesTable {...values} />
    </I18nProvider>
  </MantineProvider>
)
const names = () =>
  screen
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[1].textContent)

describe('people and infrastructure table', () => {
  it('sorts names and counts, searches group/site, and opens a real conflict action', () => {
    const values = props()
    render(view(values))
    expect(names()).toEqual(['Alpha', 'Beta', 'Zebra'])
    fireEvent.click(screen.getByRole('button', { name: 'Name' }))
    expect(names()).toEqual(['Zebra', 'Beta', 'Alpha'])
    fireEvent.change(screen.getByRole('textbox', { name: 'Find people' }), {
      target: { value: 'Plant B' },
    })
    expect(names()).toEqual(['Alpha'])
    fireEvent.click(screen.getByRole('button', { name: 'Open conflicts for Alpha' }))
    expect(values.onConflicts).toHaveBeenCalledWith(resources[1])
    fireEvent.change(screen.getByRole('textbox', { name: 'Find people' }), {
      target: { value: '' },
    })
    fireEvent.click(screen.getByRole('checkbox', { name: 'With conflicts only' }))
    expect(names()).toEqual(['Beta', 'Alpha'])
  })
  it('filters by group identity even when names collide, then combines a site filter', () => {
    render(view(props()))
    fireEvent.click(screen.getByRole('combobox', { name: 'Filter by group' }))
    fireEvent.click(screen.getAllByRole('option', { name: 'Assembly' })[1])
    expect(names()).toEqual(['Alpha', 'Beta'])
    fireEvent.click(screen.getByRole('combobox', { name: 'Filter by site' }))
    fireEvent.click(screen.getByRole('option', { name: 'No site' }))
    expect(names()).toEqual(['Beta'])
  })
  it('prunes filtered/deleted selections and hides site controls for single-plant installations', () => {
    const values = props()
    const { rerender } = render(view(values))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select visible rows' }))
    expect(screen.getByText('3 selected')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: 'With conflicts only' }))
    expect(screen.getByText('2 selected')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: 'With conflicts only' }))
    expect(screen.getByRole('checkbox', { name: 'Select Zebra' })).not.toBeChecked()
    rerender(view({ ...values, resources: [resources[1]], hasSites: false, canWrite: false }))
    expect(screen.getByText('1 selected')).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Filter by site' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New person' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }))
    expect(screen.getByRole('checkbox', { name: 'Select Alpha' })).not.toBeChecked()
  })
  it('clears the site filter when the installation stops exposing sites', () => {
    const values = props()
    const { rerender } = render(view(values))
    fireEvent.click(screen.getByRole('combobox', { name: 'Filter by site' }))
    fireEvent.click(screen.getByRole('option', { name: 'Plant B' }))
    expect(names()).toEqual(['Alpha'])
    rerender(view({ ...values, hasSites: false }))
    expect(names()).toEqual(['Alpha', 'Beta', 'Zebra'])
    expect(screen.queryByRole('combobox', { name: 'Filter by site' })).not.toBeInTheDocument()
  })
  it('hides only optional columns while keeping names and row actions', async () => {
    render(view(props()))
    fireEvent.click(screen.getByRole('button', { name: 'Columns' }))
    fireEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'Site' }))
    expect(screen.queryByRole('columnheader', { name: 'Site' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Alpha skills' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Name' })).toBeInTheDocument()
  })
})
