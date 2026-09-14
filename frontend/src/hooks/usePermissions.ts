/**
 * Hook providing permission checks derived from the current user's role and scopes.
 * Used to conditionally render edit/delete buttons and admin-only sections.
 *
 * The unified scope model uses group_ids for both personal and infrastructure.
 */

import { useAuth } from '../context/AuthContext'

/**
 * Returns permission helpers based on the authenticated user's role and scopes.
 * Admins bypass all checks, Viewers are always denied write access,
 * and Editors are checked against their configured group scopes.
 */
export function usePermissions() {
  const { user } = useAuth()

  const isAdmin = user?.role === 'admin'
  const isViewer = user?.role === 'viewer'

  /** Whether the user can edit resources in a given group. */
  const canEditGroup = (groupId: string): boolean => {
    if (isAdmin) return true
    if (isViewer) return false
    return user?.scopes.scope_group_ids?.includes(groupId) ?? false
  }

  /** Whether the user can edit a project with the given ID. */
  const canEditProject = (projectId: string): boolean => {
    if (isAdmin) return true
    if (isViewer) return false
    return user?.scopes.scope_project_ids?.includes(projectId) ?? false
  }

  /** Whether the user can manage other users (admin only). */
  const canManageUsers = isAdmin

  /** Whether the user has any write capability at all (not a viewer). */
  const canWrite = !isViewer

  return {
    isAdmin,
    isViewer,
    canEditGroup,
    canEditProject,
    canManageUsers,
    canWrite,
  }
}
