import '@testing-library/jest-dom/vitest'

import { StrictMode } from 'react'
import { MantineProvider } from '@mantine/core'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '../../i18n'
import type { ProjectFolder } from '../../types/project'
import { FolderTree } from './FolderTree'

vi.mock('./useCustomerOptions', () => ({ useCustomerOptions: () => [] }))

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
  Object.defineProperty(window, 'visualViewport', {
    writable: true,
    value: { addEventListener: vi.fn(), removeEventListener: vi.fn(), height: 768, width: 1024 },
  })
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

afterEach(cleanup)

const folder: ProjectFolder = {
  id: 'folder-1',
  name: 'Existing folder',
  parent_id: null,
  position: 2,
  external_ref: 'REF-OLD',
  customer_id: null,
  customer_name: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

describe.each(['create', 'edit'] as const)('folder %s dialog', (mode) => {
  it.each([
    { label: /^Name/, field: 'name', value: 'Projekt Müller & Söhne' },
    { label: /^Order number/, field: 'external_ref', value: 'AUF-2026-42' },
  ])('keeps repeated typing in $field and submits its value', async ({ label, field, value }) => {
    const onCreate = vi.fn().mockResolvedValue(undefined)
    const onUpdate = vi.fn().mockResolvedValue(undefined)
    const onSelect = vi.fn()
    render(
      <StrictMode>
        <MantineProvider env="test">
          <I18nProvider locale="en">
            <FolderTree
              folders={[folder]}
              projectCounts={{}}
              selectedId={null}
              onSelect={onSelect}
              onCreate={onCreate}
              onUpdate={onUpdate}
              onDelete={vi.fn()}
            />
          </I18nProvider>
        </MantineProvider>
      </StrictMode>,
    )

    if (mode === 'create') {
      fireEvent.click(screen.getByRole('button', { name: 'Folder' }))
    } else {
      fireEvent.click(screen.getByRole('button', { name: `Actions: ${folder.name}` }))
      fireEvent.click(await screen.findByRole('menuitem', { name: 'Edit' }))
    }
    expect(onSelect).not.toHaveBeenCalled()
    const dialog = within(await screen.findByRole('dialog'))
    const input = dialog.getByLabelText(label)
    // Multiple changes expose event reads deferred into React's state updater.
    for (let length = 1; length <= value.length; length++) {
      fireEvent.change(input, { target: { value: value.slice(0, length) } })
      expect(input).toHaveValue(value.slice(0, length))
    }
    if (mode === 'create' && field !== 'name') {
      fireEvent.change(dialog.getByLabelText(/^Name/), { target: { value: 'New folder' } })
    }

    fireEvent.click(dialog.getByRole('button', { name: 'Save' }))
    if (mode === 'create') {
      await waitFor(() =>
        expect(onCreate).toHaveBeenCalledExactlyOnceWith(
          field === 'name' ? value : 'New folder',
          null,
          0,
          field === 'external_ref' ? value : null,
          null,
        ),
      )
      expect(onUpdate).not.toHaveBeenCalled()
    } else {
      await waitFor(() =>
        expect(onUpdate).toHaveBeenCalledExactlyOnceWith(folder.id, {
          name: field === 'name' ? value : folder.name,
          parent_id: folder.parent_id,
          position: folder.position,
          external_ref: field === 'external_ref' ? value : folder.external_ref,
          customer_id: folder.customer_id,
        }),
      )
      expect(onCreate).not.toHaveBeenCalled()
    }
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})
