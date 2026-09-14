/**
 * Initial setup page shown when no users exist in the database.
 * Collects the first admin user credentials and basic app settings
 * (company name, primary color) in a single step.
 *
 * After successful setup, the user is logged in automatically and
 * redirected to the dashboard.
 */

import { useEffect, useState } from 'react'

import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Button,
  Center,
  ColorInput,
  Container,
  Divider,
  Image,
  Loader,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import axios from 'axios'
import { getSetupStatus, postSetup } from '../../api/setup'
import { updateTenantSettings } from '../../api/settings'
import { useAuth } from '../../context/AuthContext'
import { useSettings } from '../../context/SettingsContext'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'

const COLOR_SWATCHES = [
  '#2b6cb0',
  '#1a73e8',
  '#0d9488',
  '#059669',
  '#d97706',
  '#dc2626',
  '#7c3aed',
  '#db2777',
]

/**
 * Renders the initial setup form. Creates the first admin user and
 * configures basic application branding (company name, primary color).
 */
export function SetupPage() {
  const navigate = useNavigate()
  const { loginWithTokens } = useAuth()
  const { refreshBranding } = useSettings()
  const { t } = useTranslation()

  /**
   * Whether first-run setup is still required. A read; the redirect is a consequence of it.
   *
   * The navigation is deliberately kept in an effect rather than folded into the query: a `queryFn`
   * that navigates would run again on any refetch, and the redirect must fire once per answer, not once
   * per fetch.
   *
   * A FAILED CHECK LETS THE FORM THROUGH rather than redirecting. That is the safe direction: if the
   * endpoint cannot be reached we do not know whether an admin exists, and sending the operator to a
   * login screen they may have no account for would lock them out of their own installation. The setup
   * endpoint itself refuses a second admin, so the worst case here is a form that reports it.
   */
  const setupQuery = useQuery({
    queryKey: queryKeys.auth.setupStatus(),
    queryFn: () => getSetupStatus(),
  })
  const checking = setupQuery.isPending

  useEffect(() => {
    if (setupQuery.data && !setupQuery.data.required) {
      navigate('/login', { replace: true })
    }
  }, [setupQuery.data, navigate])

  // Admin user fields
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  // App settings fields
  const [companyName, setCompanyName] = useState('')
  const [primaryColor, setPrimaryColor] = useState('#1a73e8')

  const [error, setError] = useState<string | null>(null)

  const passwordError = password.length > 0 && password.length < 8 ? t('auth.setup.minChars') : null

  const confirmError =
    confirmPassword.length > 0 && confirmPassword !== password
      ? t('auth.setup.passwordsMismatch')
      : null

  const isValid =
    name.trim().length > 0 &&
    email.trim().length > 0 &&
    password.length >= 8 &&
    confirmPassword === password

  /**
   * FIRST-RUN SETUP IS A COMMAND with a sequence inside it, and the sequence is why this is one mutation
   * rather than three.
   *
   * The account must be created, the session established from its token, and the branding saved with
   * that token passed EXPLICITLY — the shared client's interceptor reads it from AuthContext, which has
   * not re-rendered yet in this tick. Splitting these into separate mutations would invite them to be
   * reordered or run in parallel, and the order is load-bearing.
   *
   * `refreshBranding` and the navigation are consequences, so they live in `onSuccess`. Nothing is
   * invalidated: at this point there is no cached data to be made untrue, because nothing has been read
   * yet.
   */
  const setupMutation = useMutation({
    mutationFn: async () => {
      const response = await postSetup({
        name: name.trim(),
        email: email.trim(),
        password,
      })

      // Establish the authenticated session from the setup access token FIRST,
      // so that subsequent calls to protected endpoints are authorized. The
      // refresh token is set as an httpOnly cookie by the backend.
      loginWithTokens(response.access_token)

      // Save branding settings to the backend. Pass the access token
      // explicitly: the shared client's interceptor reads the token from
      // AuthContext state, which has not re-rendered yet in this tick.
      await updateTenantSettings(
        {
          company_name: companyName.trim() || 'Capado',
          primary_color: primaryColor || 'blue',
        },
        response.access_token,
      )
    },
    onSuccess: async () => {
      await refreshBranding()
      navigate('/', { replace: true })
    },
    onError: (err: unknown) => {
      if (axios.isAxiosError(err)) {
        if (err.response?.status === 403) {
          setError(t('auth.setup.alreadyCompleted'))
          setTimeout(() => navigate('/login', { replace: true }), 2000)
        } else if (err.response?.status === 409) {
          setError(err.response?.data?.detail ?? t('auth.setup.emailExists'))
        } else {
          setError(err.response?.data?.detail ?? t('common.unexpectedError'))
        }
      } else {
        setError(t('auth.connectionError'))
      }
    },
  })
  const loading = setupMutation.isPending

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!isValid) return
    setError(null)
    setupMutation.mutate()
  }

  if (checking) {
    return (
      <Center mih="100vh">
        <Loader />
      </Center>
    )
  }

  return (
    <Center mih="100vh" py="xl">
      <Container size={480} w="100%">
        <Stack align="center" mb="md">
          <Image src="/logo.svg" alt="Capado" h={48} w="auto" fit="contain" />
        </Stack>
        <Title ta="center" mb="xs">
          {t('auth.setup.welcome')}
        </Title>
        <Text ta="center" c="dimmed" mb="lg">
          {t('auth.setup.subtitle')}
        </Text>

        <Paper withBorder shadow="md" p={30} radius="md">
          <form onSubmit={handleSubmit}>
            <Stack>
              <Title order={4}>{t('auth.setup.adminAccount')}</Title>

              <TextInput
                label={t('common.name')}
                placeholder={t('auth.setup.namePlaceholder')}
                required
                value={name}
                onChange={(e) => setName(e.currentTarget.value)}
                autoComplete="name"
              />
              <TextInput
                label={t('auth.email')}
                placeholder={t('auth.setup.emailPlaceholder')}
                required
                value={email}
                onChange={(e) => setEmail(e.currentTarget.value)}
                autoComplete="email"
              />
              <PasswordInput
                label={t('auth.password')}
                placeholder={t('auth.setup.passwordPlaceholder')}
                required
                value={password}
                onChange={(e) => setPassword(e.currentTarget.value)}
                error={passwordError}
                autoComplete="new-password"
              />
              <PasswordInput
                label={t('auth.setup.confirmPassword')}
                placeholder={t('auth.setup.confirmPasswordPlaceholder')}
                required
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.currentTarget.value)}
                error={confirmError}
                autoComplete="new-password"
              />

              <Divider my="sm" />

              <Title order={4}>{t('auth.setup.appSettings')}</Title>

              <TextInput
                label={t('auth.setup.companyName')}
                description={t('auth.setup.companyNameDesc')}
                placeholder={t('auth.setup.companyNamePlaceholder')}
                value={companyName}
                onChange={(e) => setCompanyName(e.currentTarget.value)}
              />
              <ColorInput
                label={t('auth.setup.primaryColor')}
                description={t('auth.setup.primaryColorDesc')}
                value={primaryColor}
                onChange={setPrimaryColor}
                format="hex"
                swatches={COLOR_SWATCHES}
              />

              {error && (
                <Text c="red" size="sm" role="alert">
                  {error}
                </Text>
              )}

              <Button type="submit" fullWidth loading={loading} disabled={!isValid}>
                {t('auth.setup.completeSetup')}
              </Button>
            </Stack>
          </form>
        </Paper>
      </Container>
    </Center>
  )
}
