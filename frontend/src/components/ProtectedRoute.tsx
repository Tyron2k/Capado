/**
 * Route guard that redirects unauthenticated users to /login and
 * redirects to /setup when no users exist in the database yet.
 * Stores the originally requested URL so the user can be redirected
 * back after successful authentication.
 */

import { useQuery } from '@tanstack/react-query'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Center, Loader } from '@mantine/core'
import { useAuth } from '../context/AuthContext'
import { getSetupStatus } from '../api/setup'
import { queryKeys } from '../api/queryClient'

/**
 * Wraps protected routes. Checks if initial setup is needed (no users exist),
 * then checks authentication. Redirects accordingly.
 */
export function ProtectedRoute() {
  const { user, isLoading } = useAuth()
  const location = useLocation()

  /**
   * Whether first-run setup is needed. Shares `auth.setupStatus()` with the setup page, so the guard and
   * the page it guards cannot disagree about whether an admin exists.
   *
   * Only asked when nobody is signed in: an authenticated session is proof that setup is complete, so
   * `enabled` skips the request entirely rather than asking a question whose answer is already known.
   *
   * A FAILED CHECK MEANS "SETUP NOT REQUIRED", sending the visitor to the login screen. That is the safe
   * direction HERE, and deliberately the opposite of the setup page's own fallback: this guard protects
   * the application, and defaulting to "setup needed" on a network blip would offer a stranger the
   * create-the-first-admin form on an installation that already has one. The setup endpoint refuses a
   * second admin, but the form should never be shown on a guess.
   */
  const setupQuery = useQuery({
    queryKey: queryKeys.auth.setupStatus(),
    queryFn: () => getSetupStatus(),
    enabled: !isLoading && !user,
  })

  const setupRequired = user ? false : (setupQuery.data?.required ?? false)
  const checkingSetup = !user && setupQuery.isPending && setupQuery.fetchStatus === 'fetching'

  if (isLoading || checkingSetup) {
    return (
      <Center h="100vh">
        <Loader size="lg" />
      </Center>
    )
  }

  if (setupRequired) {
    return <Navigate to="/setup" replace />
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <Outlet />
}
