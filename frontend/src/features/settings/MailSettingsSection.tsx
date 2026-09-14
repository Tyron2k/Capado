/**
 * SMTP configuration.
 *
 * Preparation, not delivery: nothing sends yet. The card says so, because a filled-in mail form
 * that silently does nothing is worse than an empty one — somebody would wait for a digest that was
 * never going to arrive.
 *
 * The password field is write-only by design. The server never returns it, so this shows whether
 * one is stored and leaves the field blank; typing nothing keeps the stored password, and an
 * explicit clear is a separate action. Prefilling a dummy value like "••••••" would be the usual
 * approach and is avoided: an operator who then edits the field around the dummy sends the dummy.
 */

import { useState } from 'react'
import {
  Alert,
  Button,
  Group,
  NumberInput,
  Paper,
  PasswordInput,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core'
import { IconAlertTriangle, IconInfoCircle } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import type { MailFormState } from './mailFormState'

interface MailSettingsSectionProps {
  state: MailFormState
  onChange: (next: MailFormState) => void
  passwordStored: boolean
  configErrors: string[]
}

export function MailSettingsSection({
  state,
  onChange,
  passwordStored,
  configErrors,
}: MailSettingsSectionProps) {
  const { t } = useTranslation()
  const [clearing, setClearing] = useState(false)
  const set = <K extends keyof MailFormState>(key: K, value: MailFormState[K]) =>
    onChange({ ...state, [key]: value })

  return (
    <Paper withBorder p="md">
      <Title order={4} mb="xs">
        {t('mail.title')}
      </Title>

      <Alert icon={<IconInfoCircle size={16} />} color="blue" variant="light" mb="sm">
        {t('mail.notSendingYet')}
      </Alert>

      {configErrors.length > 0 && (
        <Alert
          icon={<IconAlertTriangle size={16} />}
          color="orange"
          variant="light"
          mb="sm"
          title={t('mail.incomplete')}
        >
          <Stack gap={2}>
            {configErrors.map((error) => (
              <Text size="xs" key={error}>
                {error}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}

      <Stack gap="sm">
        <Switch
          label={t('mail.enabled')}
          description={t('mail.enabledDesc')}
          checked={state.smtp_enabled}
          onChange={(event) => set('smtp_enabled', event.currentTarget.checked)}
        />
        <Group grow align="flex-start">
          <TextInput
            label={t('mail.host')}
            value={state.smtp_host}
            onChange={(event) => set('smtp_host', event.currentTarget.value)}
            placeholder="relay.intern"
          />
          <NumberInput
            label={t('mail.port')}
            value={state.smtp_port}
            onChange={(value) => set('smtp_port', typeof value === 'number' ? value : '')}
            min={1}
            max={65535}
            allowDecimal={false}
          />
        </Group>
        <Switch
          label={t('mail.useTls')}
          description={t('mail.useTlsDesc')}
          checked={state.smtp_use_tls}
          onChange={(event) => set('smtp_use_tls', event.currentTarget.checked)}
        />
        <Group grow align="flex-start">
          <TextInput
            label={t('mail.username')}
            description={t('mail.usernameDesc')}
            value={state.smtp_username}
            onChange={(event) => set('smtp_username', event.currentTarget.value)}
          />
          <Stack gap={4}>
            <PasswordInput
              label={t('mail.password')}
              description={
                passwordStored && state.smtp_password === null
                  ? t('mail.passwordStored')
                  : t('mail.passwordDesc')
              }
              value={state.smtp_password ?? ''}
              onChange={(event) => set('smtp_password', event.currentTarget.value)}
            />
            {passwordStored && (
              <Button
                variant="subtle"
                color="red"
                size="compact-xs"
                onClick={() => {
                  set('smtp_password', '')
                  setClearing(true)
                }}
                disabled={clearing}
              >
                {clearing ? t('mail.passwordWillClear') : t('mail.clearPassword')}
              </Button>
            )}
          </Stack>
        </Group>
        <TextInput
          label={t('mail.fromAddress')}
          value={state.smtp_from_address}
          onChange={(event) => set('smtp_from_address', event.currentTarget.value)}
          placeholder="capado@example.invalid"
        />
        <Textarea
          label={t('mail.recipients')}
          description={t('mail.recipientsDesc')}
          value={state.digest_recipients}
          onChange={(event) => set('digest_recipients', event.currentTarget.value)}
          autosize
          minRows={2}
        />
      </Stack>
    </Paper>
  )
}
