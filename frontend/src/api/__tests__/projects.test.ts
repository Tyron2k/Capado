import { beforeEach, describe, expect, it, vi } from 'vitest'
import apiClient from '../client'
import { createProjectFolder, getProjects } from '../projects'

vi.mock('../client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

describe('project HTTP contract', () => {
  beforeEach(() => vi.clearAllMocks())

  it('unwraps every page and preserves the folder and cancellation parameters', async () => {
    const first = { id: 'a', name: 'First', customer_name: null, start_date: '2026-10-01' }
    const second = { id: 'b', name: 'Second', customer_name: 'Customer', start_date: '2026-10-02' }
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ data: { items: [first], total: 2, limit: 500, offset: 0 } })
      .mockResolvedValueOnce({ data: { items: [second], total: 2, limit: 500, offset: 1 } })
    const signal = new AbortController().signal
    expect(await getProjects(signal, 'unfiled')).toEqual([first, second])
    expect(apiClient.get).toHaveBeenNthCalledWith(2, '/api/projects', {
      signal,
      params: { limit: 500, offset: 1, folder_id: 'unfiled' },
    })
  })

  it('rejects an incomplete page rather than presenting partial data as a complete list', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { items: [], total: 2 } })
    await expect(getProjects()).rejects.toThrow('before all projects were loaded')
  })

  it('sends explicit null without inventing omitted folder properties', async () => {
    const request = { name: 'Folder', parent_id: null }
    vi.mocked(apiClient.post).mockResolvedValue({ data: { id: 'folder', ...request } })
    expect(await createProjectFolder(request)).toEqual({ id: 'folder', ...request })
    expect(apiClient.post).toHaveBeenCalledWith('/api/project-folders', request)
  })
})
