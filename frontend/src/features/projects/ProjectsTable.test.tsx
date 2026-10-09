// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import type { Project } from '../../types/project'
import { I18nProvider } from '../../i18n'
import { ProjectsTable } from './ProjectsTable'

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

const project = (
  id: string,
  name: string,
  priority: Project['priority'],
  customer: string | null,
): Project => ({
  id,
  name,
  priority,
  customer_name: customer,
  customer_id: null,
  customer_inherited: false,
  folder_id: null,
  position: 0,
  external_ref: `REF-${id}`,
  committed_delivery_date: null,
  start_date: '2026-01-01',
  end_date: '2026-12-31',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
})
const projects = [
  project('1', 'Zebra', 'low', null),
  project('2', 'Alpha', 'critical', 'ACME'),
  project('3', 'Beta', 'normal', 'ACME'),
]
function props() {
  return {
    projects,
    loading: false,
    scopeKey: null as string | null,
    canWrite: true,
    canEdit: () => true,
    onCreate: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    onOpen: vi.fn(),
  }
}
const view = (values: ReturnType<typeof props>) => (
  <MantineProvider>
    <I18nProvider locale="en">
      <ProjectsTable {...values} />
    </I18nProvider>
  </MantineProvider>
)
const names = () =>
  screen
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[1].textContent)

describe('project table pilot', () => {
  it('sorts the complete supplied set and combines customer and priority filters', () => {
    render(view(props()))
    fireEvent.click(screen.getByRole('button', { name: 'Name' }))
    expect(names()).toEqual(['Alpha', 'Beta', 'Zebra'])
    fireEvent.click(screen.getByRole('button', { name: 'Priority' }))
    expect(names()).toEqual(['Alpha', 'Beta', 'Zebra'])
    fireEvent.click(screen.getByRole('combobox', { name: 'Customer' }))
    fireEvent.click(screen.getByRole('option', { name: 'ACME' }))
    expect(names()).toEqual(['Alpha', 'Beta'])
    fireEvent.click(screen.getByRole('combobox', { name: 'Priority' }))
    fireEvent.click(screen.getByRole('option', { name: 'Critical' }))
    expect(names()).toEqual(['Alpha'])
  })

  it('hides columns without dropping their filters', async () => {
    render(view(props()))
    fireEvent.click(screen.getByRole('combobox', { name: 'Customer' }))
    fireEvent.click(screen.getByRole('option', { name: 'ACME' }))
    fireEvent.click(screen.getByRole('button', { name: 'Columns' }))
    fireEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'Customer' }))
    expect(screen.queryByRole('columnheader', { name: 'Customer' })).not.toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: 'Search projects…' }), {
      target: { value: 'REF-2' },
    })
    expect(names()).toEqual(['Alpha'])
  })

  it('distinguishes internal work from a customer whose name resembles a filter key', () => {
    render(
      view({
        ...props(),
        projects: [...projects, project('4', 'Named customer', 'low', '__internal')],
      }),
    )
    fireEvent.click(screen.getByRole('combobox', { name: 'Customer' }))
    fireEvent.click(screen.getByRole('option', { name: 'Internal work' }))
    expect(names()).toEqual(['Zebra'])
  })

  it('prunes hidden selections and clears selection on a folder change', () => {
    const values = props()
    const { rerender } = render(view(values))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select visible projects' }))
    expect(screen.getByText('3 selected')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: 'Search projects…' }), {
      target: { value: 'Alpha' },
    })
    expect(screen.getByText('1 selected')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: 'Search projects…' }), {
      target: { value: '' },
    })
    expect(screen.getByRole('checkbox', { name: 'Select Zebra' })).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Select Alpha' })).toBeChecked()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Show selected only' }))
    expect(names()).toEqual(['Alpha'])
    rerender(view({ ...values, scopeKey: 'folder-2' }))
    expect(screen.queryByText('1 selected')).not.toBeInTheDocument()
    expect(names()).toEqual(['Zebra', 'Alpha', 'Beta'])
  })

  it('keeps an active customer filter visible when a folder has no matching customer', () => {
    const values = props()
    const { rerender } = render(view(values))
    fireEvent.click(screen.getByRole('combobox', { name: 'Customer' }))
    fireEvent.click(screen.getByRole('option', { name: 'ACME' }))
    rerender(view({ ...values, projects: [projects[0]], scopeKey: 'internal-folder' }))
    expect(screen.getByRole('combobox', { name: 'Customer' })).toHaveValue('ACME')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('removes deleted IDs from selection and only exposes permitted actions', () => {
    const values = { ...props(), canWrite: false, canEdit: () => false }
    const { rerender } = render(view(values))
    expect(screen.queryByRole('button', { name: 'New Project' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit project' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete project' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select Alpha' }))
    rerender(view({ ...values, projects: [projects[0], projects[2]] }))
    expect(screen.queryByText('1 selected')).not.toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Show work packages' })[0])
    expect(values.onOpen).toHaveBeenCalledWith(projects[0])
  })
})
