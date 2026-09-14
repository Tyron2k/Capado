/**
 * Tests for the self-service API client.
 *
 * These exist because of a bug that shipped: the path was '/me/plan' instead of '/api/me/plan'.
 * apiClient has an empty baseURL, so that request never reached the backend — the frontend's
 * catch-all route answered 200 with index.html, axios reported success, and the page crashed on
 * `plan.assignments.length` because the "plan" was an HTML string.
 *
 * The page test did not catch it because it mocks getMyPlan itself, so the URL was never exercised.
 * The mock boundary here is deliberately one level lower: the client is real, only the transport is
 * faked, which is the only place the URL can be asserted at all.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./client', () => ({
  default: { get: vi.fn() },
}))

const apiClient = (await import('./client')).default
const { getMyPlan, NoLinkedResourceError } = await import('./me')
const mockedGet = vi.mocked(apiClient.get)

const plan = {
  resource_id: 'r-1',
  assignments: [],
  assignment_total: 0,
  absences: [],
  absence_total: 0,
  skills: [],
}

describe('getMyPlan', () => {
  beforeEach(() => {
    mockedGet.mockReset()
  })

  it('calls the API under the /api prefix', async () => {
    mockedGet.mockResolvedValue({ data: plan })

    await getMyPlan()

    // Not a style assertion: without the prefix the frontend's catch-all serves index.html with a
    // 200, so the failure is silent and surfaces as a render crash somewhere else entirely.
    expect(mockedGet).toHaveBeenCalledWith('/api/me/plan')
  })

  it('returns the plan body unchanged', async () => {
    mockedGet.mockResolvedValue({ data: plan })

    await expect(getMyPlan()).resolves.toEqual(plan)
  })

  it('translates a 409 into NoLinkedResourceError', async () => {
    mockedGet.mockRejectedValue({ response: { status: 409 } })

    await expect(getMyPlan()).rejects.toBeInstanceOf(NoLinkedResourceError)
  })

  it('lets any other failure through untouched', async () => {
    const boom = { response: { status: 500 } }
    mockedGet.mockRejectedValue(boom)

    // Must NOT become NoLinkedResourceError: the page renders that state as "an administrator has
    // to link your account", which would be a lie about a server fault.
    await expect(getMyPlan()).rejects.toBe(boom)
  })
})
