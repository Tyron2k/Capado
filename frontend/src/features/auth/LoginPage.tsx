/**
 * Login page with email and password form.
 * Redirects to the originally requested URL on successful authentication.
 * Optionally shows an SSO button when OIDC is configured.
 */

import { useEffect, useState } from 'react'

import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate, useLocation, useSearchParams } from 'react-router-dom'
import {
  Button,
  Center,
  Container,
  Divider,
  Image,
  Paper,
  Stack,
  Text,
  TextInput,
  PasswordInput,
} from '@mantine/core'
import { IconLock } from '@tabler/icons-react'
import axios from 'axios'
import { useAuth } from '../../context/AuthContext'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { getOIDCLoginUrl, getOIDCStatus } from '../../api/oidc'

/**
 * Renders the login form with optional SSO button. On successful login,
 * navigates to the URL the user originally requested (stored in location
 * state) or the dashboard.
 */
export function LoginPage() {
  const { login, user, isLoading: authLoading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const { t } = useTranslation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || '/'

  // Check for OIDC error from callback redirect
  useEffect(() => {
    const oidcError = searchParams.get('error')
    if (oidcError) {
      setError(t('auth.oidc.error'))
    }
  }, [searchParams, t])

  /**
   * Whether single sign-on is offered. A READ, so it goes through the cache like any other.
   *
   * Nothing ever invalidates it: it is answered once on a page the user leaves permanently as soon as
   * they get past it. It is a query so this screen uses one mechanism instead of a second hand-written
   * one — not because it takes part in the invalidation graph.
   *
   * Failure means "no SSO button", which is the right answer when the endpoint cannot be reached: the
   * password form beside it still works.
   */
  const oidcQuery = useQuery({
    queryKey: queryKeys.auth.oidcStatus(),
    queryFn: () => getOIDCStatus(),
  })
  const oidcEnabled = oidcQuery.data?.enabled ?? false

  // Redirect if already logged in
  useEffect(() => {
    if (!authLoading && user) {
      navigate(from, { replace: true })
    }
  }, [authLoading, user, navigate, from])

  /**
   * SIGNING IN IS A COMMAND, NOT A READ, and this is where the migration draws its own boundary.
   *
   * There is no cached value here and nothing to invalidate: a login does not make some other screen's
   * data untrue, it decides who is asking. `useMutation` is used all the same, because it is the right
   * home for a one-shot write — it owns the pending flag that was hand-rolled as `setLoading`, which is
   * the whole benefit. Reaching for `useQuery` here would have been cargo cult.
   *
   * The bespoke error mapping is kept verbatim: 401 is wrong credentials, 403 is an account that exists
   * but may not enter, and both are more useful than a generic failure on a sign-in screen.
   */
  const loginMutation = useMutation({
    mutationFn: () => login(email, password),
    onSuccess: () => navigate(from, { replace: true }),
    onError: (err: unknown) => {
      if (axios.isAxiosError(err)) {
        if (err.response?.status === 401) {
          setError(t('auth.invalidCredentials'))
        } else if (err.response?.status === 403) {
          setError(err.response?.data?.detail ?? t('auth.accessDenied'))
        } else {
          setError(err.response?.data?.detail ?? t('auth.unexpectedError'))
        }
      } else {
        setError(t('auth.connectionError'))
      }
    },
  })
  const loading = loginMutation.isPending

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    loginMutation.mutate()
  }

  function handleSSOLogin() {
    window.location.href = getOIDCLoginUrl()
  }

  return (
    <Center h="100vh">
      <Container size={420} w="100%">
        <Stack align="center" mb="lg">
          <Image src="/logo.svg" alt="Capado" h={48} w="auto" fit="contain" />
        </Stack>

        <Paper withBorder shadow="md" p={30} radius="md">
          <Stack>
            {oidcEnabled && (
              <>
                <Button
                  fullWidth
                  variant="default"
                  leftSection={<IconLock size={18} />}
                  onClick={handleSSOLogin}
                >
                  {t('auth.oidc.signInWithSSO')}
                </Button>
                <Divider label={t('auth.oidc.or')} labelPosition="center" />
              </>
            )}
            <form onSubmit={handleSubmit}>
              <Stack>
                <TextInput
                  label={t('auth.email')}
                  placeholder={t('auth.emailPlaceholder')}
                  required
                  value={email}
                  onChange={(e) => setEmail(e.currentTarget.value)}
                  autoComplete="email"
                />
                <PasswordInput
                  label={t('auth.password')}
                  placeholder={t('auth.passwordPlaceholder')}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.currentTarget.value)}
                  autoComplete="current-password"
                />
                {error && (
                  <Text c="red" size="sm" role="alert">
                    {error}
                  </Text>
                )}
                <Button type="submit" fullWidth loading={loading}>
                  {t('auth.signIn')}
                </Button>
              </Stack>
            </form>
          </Stack>
        </Paper>
      </Container>
    </Center>
  )
}
