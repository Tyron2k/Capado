/**
 * Non-dismissible modal that forces a password change when the user's
 * must_change_password flag is set. Requires current password, new password,
 * and confirmation. Validates minimum length (8 chars) and match before
 * submitting to the change-password endpoint.
 */

import { useState } from 'react'

import { useMutation } from '@tanstack/react-query'
import { Button, Modal, PasswordInput, Stack, Text } from '@mantine/core'
import axios from 'axios'
import { postChangePassword } from '../../api/auth'
import { useAuth } from '../../context/AuthContext'
import { useTranslation } from '../../i18n'

/**
 * Renders a non-dismissible modal requiring the user to change their password.
 * Cannot be closed without successfully changing the password.
 */
export function ChangePasswordModal() {
  const { accessToken, clearMustChangePassword } = useAuth()
  const { t } = useTranslation()

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const newPasswordError =
    newPassword.length > 0 && newPassword.length < 8 ? t('auth.changePassword.minChars') : null

  const confirmPasswordError =
    confirmPassword.length > 0 && confirmPassword !== newPassword
      ? t('auth.changePassword.passwordsMismatch')
      : null

  const isValid =
    currentPassword.length > 0 && newPassword.length >= 8 && confirmPassword === newPassword

  /**
   * A COMMAND. Nothing is cached and nothing is invalidated — a changed password does not make any
   * screen's data untrue. `useMutation` is here for the pending flag it owns, not for a cache.
   *
   * 401 means the CURRENT password was wrong, which is a correctable mistake and not a failure worth a
   * generic message.
   */
  const changeMutation = useMutation({
    mutationFn: () => postChangePassword(currentPassword, newPassword, accessToken!),
    onSuccess: () => clearMustChangePassword(),
    onError: (err: unknown) => {
      if (axios.isAxiosError(err)) {
        if (err.response?.status === 401) {
          setError(t('auth.changePassword.incorrectPassword'))
        } else {
          setError(err.response?.data?.detail ?? t('common.unexpectedError'))
        }
      } else {
        setError(t('auth.connectionError'))
      }
    },
  })
  const loading = changeMutation.isPending

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!isValid || !accessToken) return
    setError(null)
    changeMutation.mutate()
  }

  return (
    <Modal
      opened
      onClose={() => {}}
      closeOnClickOutside={false}
      closeOnEscape={false}
      withCloseButton={false}
      title={t('auth.changePassword.title')}
      centered
    >
      <form onSubmit={handleSubmit}>
        <Stack>
          <Text size="sm" c="dimmed">
            {t('auth.changePassword.description')}
          </Text>
          <PasswordInput
            label={t('auth.changePassword.currentPassword')}
            placeholder={t('auth.changePassword.currentPasswordPlaceholder')}
            required
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.currentTarget.value)}
            autoComplete="current-password"
          />
          <PasswordInput
            label={t('auth.changePassword.newPassword')}
            placeholder={t('auth.changePassword.newPasswordPlaceholder')}
            required
            value={newPassword}
            onChange={(e) => setNewPassword(e.currentTarget.value)}
            error={newPasswordError}
            autoComplete="new-password"
          />
          <PasswordInput
            label={t('auth.changePassword.confirmNewPassword')}
            placeholder={t('auth.changePassword.confirmNewPasswordPlaceholder')}
            required
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.currentTarget.value)}
            error={confirmPasswordError}
            autoComplete="new-password"
          />
          {error && (
            <Text c="red" size="sm" role="alert">
              {error}
            </Text>
          )}
          <Button type="submit" fullWidth loading={loading} disabled={!isValid}>
            {t('auth.changePassword.submit')}
          </Button>
        </Stack>
      </form>
    </Modal>
  )
}
