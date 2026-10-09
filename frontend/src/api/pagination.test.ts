import { describe, expect, it, vi } from 'vitest'
import { allPages } from './pagination'

describe('complete API collections', () => {
  it('continues from the actual number received until the total is loaded', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({ items: ['a', 'b'], total: 3 })
      .mockResolvedValueOnce({ items: ['c'], total: 3 })
    expect(await allPages(fetch)).toEqual(['a', 'b', 'c'])
    expect(fetch.mock.calls).toEqual([[0], [2]])
  })
  it('refuses a truncated empty page and propagates cancellation', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({ items: ['a'], total: 3 })
      .mockResolvedValueOnce({ items: [], total: 3 })
    await expect(allPages(fetch)).rejects.toThrow('before all entries')
    const aborted = new DOMException('Cancelled', 'AbortError')
    await expect(allPages(vi.fn().mockRejectedValue(aborted))).rejects.toBe(aborted)
  })
})
