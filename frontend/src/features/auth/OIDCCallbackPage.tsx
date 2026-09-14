/**
 * Handles the OIDC callback redirect from the backend.
 * Extracts the access_token from URL params (the refresh token is set as an
 * httpOnly cookie by the backend), establishes the session, and redirects to
 * the dashboard.
 */

import { useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Center, Loader, Stack, Text } from '@mantine/core'
import { useAuth } from '../../context/AuthContext'
import { useTranslation } from '../../i18n'

/**
 * OIDC callback page that receives tokens from the backend redirect
 * and establishes the frontend session.
 */
export function OIDCCallbackPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { loginWithTokens } = useAuth()
  const { t } = useTranslation()
  const processedRef = useRef(false)

  useEffect(() => {
    if (processedRef.current) return
    processedRef.current = true

    const accessToken = searchParams.get('access_token')
    const error = searchParams.get('error')

    if (error) {
      navigate('/login?error=' + error, { replace: true })
      return
    }

    if (accessToken) {
      loginWithTokens(accessToken)
      navigate('/', { replace: true })
    } else {
      navigate('/login?error=oidc_missing_tokens', { replace: true })
    }
  }, [searchParams, navigate, loginWithTokens])

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
