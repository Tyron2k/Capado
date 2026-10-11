/**
 * Handles the OIDC callback redirect from the backend.
 * Waits for AuthProvider to restore the session from the HttpOnly cookie.
 * The redirect URL carries no credentials.
 */

import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Center, Loader, Stack, Text } from '@mantine/core'
import { useAuth } from '../../context/AuthContext'
import { useTranslation } from '../../i18n'

/**
 * AuthProvider owns the single initial refresh, including on this page.
 */
export function OIDCCallbackPage() {
  const navigate = useNavigate()
  const { isLoading, user } = useAuth()
  const { t } = useTranslation()
  const processedRef = useRef(false)

  useEffect(() => {
    if (isLoading || processedRef.current) return
    processedRef.current = true

    navigate(user ? '/' : '/login?error=oidc_session_failed', { replace: true })
  }, [isLoading, user, navigate])

  return (
    <Center h="100vh">
      <Stack align="center">
        <Loader size="lg" />
        <Text size="sm" c="dimmed">
          {t('auth.oidc.processing')}
        </Text>
      </Stack>
    </Center>
  )
}
