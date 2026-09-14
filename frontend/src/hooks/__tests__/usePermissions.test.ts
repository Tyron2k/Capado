/**
 * Property-based tests for the usePermissions hook.
 *
 * Covers RBAC permission logic:
 * - Admin role bypasses all checks (always true)
 * - Viewer role is denied all write operations (always false)
 * - Editor role is granted access only within configured group scopes
 * - Editor without scopes is denied all scope-based checks
 *
 * Uses fast-check to generate arbitrary group IDs and project IDs
 * to verify permission invariants hold universally.
 */

// @vitest-environment jsdom

import { renderHook } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as fc from 'fast-check'

// Mock the AuthContext module so usePermissions gets our controlled user data
vi.mock('../../context/AuthContext', () => ({
  useAuth: vi.fn(),
}))

import { useAuth } from '../../context/AuthContext'
import { usePermissions } from '../usePermissions'

const mockedUseAuth = vi.mocked(useAuth)

// --- Generators ---

/** Generates a UUID-like group ID. */
const groupIdArb = fc.uuid()

/** Generates a UUID-like project ID. */
const projectIdArb = fc.uuid()

/** Generates a list of 1-5 group IDs. */
const groupIdsListArb = fc.array(groupIdArb, { minLength: 1, maxLength: 5 })

/** Generates a list of 1-5 project IDs. */
const projectIdsListArb = fc.array(projectIdArb, { minLength: 1, maxLength: 5 })

// --- Helpers ---

function mockUser(
  role: string,
  scopes: {
    scope_group_ids?: string[] | null
    scope_project_ids?: string[] | null
  },
) {
  mockedUseAuth.mockReturnValue({
    user: {
      id: 'test-user-id',
      email: 'test@example.com',
      name: 'Test User',
      role,
      must_change_password: false,
      scopes: {
        scope_group_ids: scopes.scope_group_ids ?? null,
        scope_project_ids: scopes.scope_project_ids ?? null,
      },
    },
    accessToken: 'fake-token',
    isLoading: false,
    login: vi.fn(),
    loginWithTokens: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
    clearMustChangePassword: vi.fn(),
  })
}

// --- Property Tests ---

describe('usePermissions — property-based tests', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('Property: Admin always returns true for all permission checks', () => {
    fc.assert(
      fc.property(groupIdArb, projectIdArb, (groupId, projId) => {
        mockUser('admin', {})

        const { result } = renderHook(() => usePermissions())

        expect(result.current.isAdmin).toBe(true)
        expect(result.current.canWrite).toBe(true)
        expect(result.current.canManageUsers).toBe(true)
        expect(result.current.canEditGroup(groupId)).toBe(true)
        expect(result.current.canEditProject(projId)).toBe(true)
      }),
      { numRuns: 50 },
    )
  })

  it('Property: Viewer always returns false for all write permission checks', () => {
    fc.assert(
      fc.property(groupIdArb, projectIdArb, (groupId, projId) => {
        mockUser('viewer', {
          scope_group_ids: [groupId],
          scope_project_ids: [projId],
        })

        const { result } = renderHook(() => usePermissions())

        expect(result.current.isViewer).toBe(true)
        expect(result.current.canWrite).toBe(false)
        expect(result.current.canManageUsers).toBe(false)
        expect(result.current.canEditGroup(groupId)).toBe(false)
        expect(result.current.canEditProject(projId)).toBe(false)
      }),
      { numRuns: 50 },
    )
  })

  it('Property: Editor with matching group ID returns true for canEditGroup', () => {
    fc.assert(
      fc.property(groupIdsListArb, (groupIds) => {
        mockUser('editor', { scope_group_ids: groupIds })

        const { result } = renderHook(() => usePermissions())

        // Every group in the scope list should be allowed
        for (const gid of groupIds) {
          expect(result.current.canEditGroup(gid)).toBe(true)
        }
      }),
      { numRuns: 50 },
    )
  })

  it('Property: Editor with non-matching group ID returns false for canEditGroup', () => {
    fc.assert(
      fc.property(groupIdsListArb, groupIdArb, (scopedGroups, queryGroup) => {
        // Ensure the query group is NOT in the scoped list
        fc.pre(!scopedGroups.includes(queryGroup))

        mockUser('editor', { scope_group_ids: scopedGroups })

        const { result } = renderHook(() => usePermissions())

        expect(result.current.canEditGroup(queryGroup)).toBe(false)
      }),
      { numRuns: 50 },
    )
  })

  it('Property: Editor with matching project ID returns true for canEditProject', () => {
    fc.assert(
      fc.property(projectIdsListArb, (projectIds) => {
        mockUser('editor', { scope_project_ids: projectIds })

        const { result } = renderHook(() => usePermissions())

        for (const pid of projectIds) {
          expect(result.current.canEditProject(pid)).toBe(true)
        }
      }),
      { numRuns: 50 },
    )
  })

  it('Property: Editor without any scopes returns false for all scope checks', () => {
    fc.assert(
      fc.property(groupIdArb, projectIdArb, (groupId, projId) => {
        mockUser('editor', {
          scope_group_ids: null,
          scope_project_ids: null,
        })

        const { result } = renderHook(() => usePermissions())

        expect(result.current.canWrite).toBe(true) // editors can write in general
        expect(result.current.canManageUsers).toBe(false)
        expect(result.current.canEditGroup(groupId)).toBe(false)
        expect(result.current.canEditProject(projId)).toBe(false)
      }),
      { numRuns: 50 },
    )
  })
})
