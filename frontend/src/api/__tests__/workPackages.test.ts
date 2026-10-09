import { beforeEach, describe, expect, it, vi } from 'vitest'
import apiClient from '../client'
import { createWorkPackage, getWorkPackages } from '../workPackages'

vi.mock('../client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

describe('work-package HTTP contract', () => {
  beforeEach(() => vi.clearAllMocks())

  it('unwraps every page while preserving serialized dates and null completion', async () => {
    const first = { id: 'a', name: 'First', start_date: '2026-10-01', completed_at: null }
    const second = { id: 'b', name: 'Second', start_date: '2026-10-02', completed_at: null }
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ data: { items: [first], total: 2 } })
      .mockResolvedValueOnce({ data: { items: [second], total: 2 } })
    expect(await getWorkPackages('project')).toEqual([first, second])
    expect(apiClient.get).toHaveBeenNthCalledWith(2, '/api/projects/project/work-packages', {
      params: { limit: 500, offset: 1 },
    })
  })

  it('rejects an incomplete page instead of exposing a partial set', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { items: [], total: 2 } })
    await expect(getWorkPackages('project')).rejects.toThrow('before all work packages were loaded')
  })

  it('preserves the write warning envelope', async () => {
    const request = { name: 'Paint', start_date: '2026-10-01', end_date: '2026-10-02' }
    const response = {
      work_package: { ...request, id: 'package' },
      warnings: ['Insufficient lead time'],
    }
    vi.mocked(apiClient.post).mockResolvedValue({ data: response })
    expect(await createWorkPackage('project', request)).toEqual(response)
    expect(apiClient.post).toHaveBeenCalledWith('/api/projects/project/work-packages', request)
  })
})
