// @vitest-environment jsdom

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import apiClient from '../../api/client'
import { ImportExportBar } from './ImportExportBar'
import { CsvAreaBar } from './CsvAreaBar'
import { notifications } from '@mantine/notifications'

vi.mock('../../i18n', () => ({
  useTranslation: () => ({ locale: 'en', t: (key: string) => key }),
}))
vi.mock('../../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

beforeAll(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe = vi.fn()
      unobserve = vi.fn()
      disconnect = vi.fn()
    },
  )
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
beforeEach(() => vi.clearAllMocks())

function toolbar(csvBundle = true) {
  const client = new QueryClient()
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const rendered = render(
    <MantineProvider>
      <QueryClientProvider client={client}>
        <ImportExportBar
          exportPath="/api/migration/export"
          importPath="/api/migration/import"
          filenameBase="capado-csv"
          csvBundle={csvBundle}
        />
      </QueryClientProvider>
    </MantineProvider>,
  )
  return { ...rendered, invalidate }
}

describe('complete CSV migration toolbar', () => {
  it('shows the backend field diagnostic from a failed blob download', async () => {
    const detail = 'history.csv, row 4, field payload: exceeds the 4 MiB field limit.'
    const body = new Blob([JSON.stringify({ detail })], { type: 'application/json' })
    Object.defineProperty(body, 'text', { value: async () => JSON.stringify({ detail }) })
    vi.mocked(apiClient.get).mockRejectedValueOnce({ isAxiosError: true, response: { data: body } })
    const notify = vi.spyOn(notifications, 'show').mockImplementation(() => 'test-notification')
    toolbar()
    fireEvent.click(screen.getByLabelText('importExport.export'))
    fireEvent.click(await screen.findByText('importExport.formatCsvBundle'))
    await waitFor(() =>
      expect(notify).toHaveBeenCalledWith({ title: 'common.error', message: detail, color: 'red' }),
    )
    notify.mockRestore()
  })

  it('uploads the whole ZIP and refreshes all cached data after success', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: {
        created: 27,
        updated: 1,
        skipped: 0,
        errors: [],
        success: true,
      },
    })
    const { container, invalidate } = toolbar()
    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    expect(input.accept).toBe('.zip')
    const file = new File(['archive'], 'capado-csv.zip', { type: 'application/zip' })
    fireEvent.change(input, { target: { files: [file] } })
    expect(await screen.findByText('importExport.logNoErrors')).toBeInTheDocument()
    expect(screen.getByText('importExport.created: 27')).toBeInTheDocument()
    const [path, data] = vi.mocked(apiClient.post).mock.calls[0]
    expect(path).toBe('/api/migration/import')
    expect((data as FormData).get('file')).toBe(file)
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith())
    expect(input.value).toBe('')
  })

  it('downloads a ZIP with a matching filename and offers only the package format', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: new Blob(['archive']) })
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:csv-migration'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    toolbar()
    fireEvent.click(screen.getByLabelText('importExport.export'))
    fireEvent.click(await screen.findByText('importExport.formatCsvBundle'))
    await waitFor(() => expect(click).toHaveBeenCalledOnce())
    expect(vi.mocked(apiClient.get)).toHaveBeenCalledWith('/api/migration/export?format=csv-zip', {
      responseType: 'blob',
    })
    expect((click.mock.contexts[0] as HTMLAnchorElement).download).toBe('capado-csv.zip')
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:csv-migration')
    expect(screen.queryByText('importExport.formatMatrix')).not.toBeInTheDocument()
    click.mockRestore()
  })

  it.each([true, false])(
    'shows accurate rejection semantics (complete bundle: %s)',
    async (csvBundle) => {
      vi.mocked(apiClient.post).mockResolvedValue({
        data: {
          created: csvBundle ? 0 : 1,
          updated: 0,
          skipped: 0,
          errors: ['Invalid data'],
          success: false,
        },
      })
      const { container, invalidate } = toolbar(csvBundle)
      fireEvent.change(container.querySelector('input[type="file"]')!, {
        target: { files: [new File(['bad'], csvBundle ? 'bad.zip' : 'bad.csv')] },
      })
      expect(await screen.findByText('Invalid data')).toBeInTheDocument()
      expect(
        screen.getByText(
          csvBundle ? 'importExport.bundleRejectedBody' : 'importExport.logRejectedBody',
        ),
      ).toBeInTheDocument()
      expect(invalidate).not.toHaveBeenCalledWith()
    },
  )
})

it('an individual CSV rejection uses the server atomic result and refreshes every area on success', async () => {
  const client = new QueryClient()
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const { container } = render(
    <MantineProvider>
      <QueryClientProvider client={client}>
        <CsvAreaBar area="skills" />
      </QueryClientProvider>
    </MantineProvider>,
  )
  const input = container.querySelector('input[type="file"]') as HTMLInputElement
  expect(input.accept).toBe('.csv')
  vi.mocked(apiClient.post).mockResolvedValueOnce({
    data: { success: false, atomic: true, errors: ['Unknown reference'], created: 0, updated: 0 },
  })
  fireEvent.change(input, { target: { files: [new File(['bad'], 'skills.csv')] } })
  expect(await screen.findByText('importExport.bundleRejectedBody')).toBeInTheDocument()
  expect(invalidate).not.toHaveBeenCalledWith()
  fireEvent.click(screen.getByText('importExport.logClose'))
  vi.mocked(apiClient.post).mockResolvedValueOnce({
    data: { success: true, atomic: true, errors: [], created: 1, updated: 2 },
  })
  fireEvent.change(input, { target: { files: [new File(['valid'], 'skills.csv')] } })
  expect(await screen.findByText('importExport.logNoErrors')).toBeInTheDocument()
  expect(vi.mocked(apiClient.post).mock.calls[0][0]).toBe('/api/data/skills/import')
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith())
})
