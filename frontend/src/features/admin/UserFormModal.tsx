/**
 * Modal form for creating or editing a user. Shows role select and
 * scope multi-selects (groups, projects) loaded from API.
 * Scope fields are only visible when the role is "editor".
 *
 * Two fields appear only when EDITING, because they act on an account that already exists:
 *
 * `resource_id` links the account to the scheduled person it belongs to, which is what lets that
 * person read their own plan. Left empty it stays as it was — clearing it is a separate flag, so a
 * rename cannot silently unlink somebody from their own schedule.
 *
 * `password` resets it. Filled in, the user is forced to replace it at next login: the admin knows
 * this value, so it is a handover credential rather than a password. There is no self-service reset
 * in Capado, which is why this is here at all.
 */

import { useEffect, useMemo } from 'react'

import { useQuery } from '@tanstack/react-query'
import { Button, Group, Modal, MultiSelect, PasswordInput, Select, TextInput } from '@mantine/core'
import { useForm } from '@mantine/form'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { getProjects } from '../../api/projects'
import { getGroups, getPersonalTree } from '../../api/resources'
import type { User, UserCreateData, UserUpdateData } from '../../api/users'

interface UserFormModalProps {
  opened: boolean
  onClose: () => void
  onSubmit: (data: UserCreateData | UserUpdateData) => Promise<void>
  user: User | null
  loading?: boolean
}

interface FormValues {
  name: string
  email: string
  password: string
  role: string
  scope_group_ids: string[]
  scope_project_ids: string[]
  /** Empty string means "no person selected", which on edit means "leave the link alone". */
  resource_id: string
  /** Only sent when non-empty; resets the password and forces a change at next login. */
  newPassword: string
}

/**
 * Renders a modal with a form for creating or editing a user.
 * Loads available groups and projects for scope multi-selects.
 */
export function UserFormModal({
  opened,
  onClose,
  onSubmit,
  user,
  loading = false,
}: UserFormModalProps) {
  const { t } = useTranslation()
  const isEditing = user !== null

  const form = useForm<FormValues>({
    initialValues: {
      name: '',
      email: '',
      password: '',
      role: 'viewer',
      scope_group_ids: [],
      scope_project_ids: [],
      resource_id: '',
      newPassword: '',
    },
    validate: {
      name: (value) => (value.trim().length === 0 ? t('userManagement.form.nameRequired') : null),
      email: (value) => {
        if (!isEditing && value.trim().length === 0) return t('userManagement.form.emailRequired')
        if (!isEditing && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value))
          return t('userManagement.form.emailInvalid')
        return null
      },
      password: (value) => {
        if (!isEditing && value.length < 8) return t('userManagement.form.passwordMin')
        return null
      },
      // Empty means "do not reset", so only a non-empty value is length-checked. Eight characters
      // matches the backend rather than inventing a second rule.
      newPassword: (value) =>
        value.length > 0 && value.length < 8 ? t('userManagement.form.passwordMin') : null,
      role: (value) => (value ? null : t('userManagement.form.roleRequired')),
    },
  })

  /**
   * THREE PICKERS, THREE QUERIES, all gated on `opened` — the modal must not fetch three lists while it
   * is closed, which is what the `if (!opened) return` guard did.
   *
   * All three still degrade to an empty picker on failure: a scope is optional, and an empty list says
   * "no scope restriction" more usefully than a notification behind a form would.
   */
  const groupsQuery = useQuery({
    queryKey: queryKeys.resources.groups('all'),
    queryFn: () => getGroups(),
    enabled: opened,
  })
  const projectsQuery = useQuery({
    queryKey: queryKeys.projects.list(),
    queryFn: () => getProjects(),
    enabled: opened,
  })
  const peopleQuery = useQuery({
    queryKey: queryKeys.resources.personalTree(),
    queryFn: () => getPersonalTree(),
    enabled: opened,
  })

  const groupOptions = useMemo(
    () => (groupsQuery.data ?? []).map((g) => ({ value: g.id, label: g.name })),
    [groupsQuery.data],
  )
  const projectOptions = useMemo(
    () => (projectsQuery.data ?? []).map((p) => ({ value: p.id, label: p.name })),
    [projectsQuery.data],
  )
  const personOptions = useMemo(
    () => (peopleQuery.data ?? []).map((p) => ({ value: p.id, label: p.name })),
    [peopleQuery.data],
  )

  useEffect(() => {
    if (!opened) return

    if (user) {
      form.setValues({
        name: user.name,
        email: user.email,
        password: '',
        role: user.role,
        scope_group_ids: user.scope_group_ids ?? [],
        scope_project_ids: user.scope_project_ids ?? [],
        resource_id: user.resource_id ?? '',
        newPassword: '',
      })
    } else {
      form.reset()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, user])

  const handleSubmit = async (values: FormValues) => {
    if (isEditing) {
      const data: UserUpdateData = {
        name: values.name.trim(),
        role: values.role as 'admin' | 'editor' | 'viewer',
        scope_group_ids: values.role === 'editor' ? values.scope_group_ids : null,
        scope_project_ids: values.role === 'editor' ? values.scope_project_ids : null,
      }
      // Only ever SEND a password when one was typed. Sending an empty string would reset the
      // account to an unusable value on every unrelated edit.
      if (values.newPassword.length > 0) {
        data.password = values.newPassword
      }
      // Three cases, and the difference matters: a person chosen links, an emptied field on a
      // previously linked account clears, and no change at all sends nothing.
      const hadLink = user?.resource_id ?? ''
      if (values.resource_id !== hadLink) {
        if (values.resource_id === '') {
          data.clear_resource_id = true
        } else {
          data.resource_id = values.resource_id
        }
      }
      await onSubmit(data)
    } else {
      const data: UserCreateData = {
        name: values.name.trim(),
        email: values.email.trim(),
        password: values.password,
        role: values.role as 'admin' | 'editor' | 'viewer',
        ...(values.role === 'editor' && {
          scope_group_ids: values.scope_group_ids.length > 0 ? values.scope_group_ids : undefined,
          scope_project_ids:
            values.scope_project_ids.length > 0 ? values.scope_project_ids : undefined,
        }),
      }
      await onSubmit(data)
    }
  }

  const roleOptions = [
    { value: 'admin', label: t('userManagement.form.roleAdmin') },
    { value: 'editor', label: t('userManagement.form.roleEditor') },
    { value: 'viewer', label: t('userManagement.form.roleViewer') },
  ]

  const showScopes = form.values.role === 'editor'

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={isEditing ? t('userManagement.editUser') : t('userManagement.createUser')}
      size="md"
    >
      <form onSubmit={form.onSubmit(handleSubmit)}>
        <TextInput
          label={t('common.name')}
          placeholder={t('userManagement.form.namePlaceholder')}
          required
          mb="sm"
          {...form.getInputProps('name')}
        />

        {!isEditing && (
          <TextInput
            label={t('userManagement.form.email')}
            placeholder={t('userManagement.form.emailPlaceholder')}
            required
            mb="sm"
            {...form.getInputProps('email')}
          />
        )}

        {!isEditing && (
          <PasswordInput
            label={t('userManagement.form.password')}
            placeholder={t('userManagement.form.passwordPlaceholder')}
            required
            mb="sm"
            {...form.getInputProps('password')}
          />
        )}

        <Select
          label={t('userManagement.form.role')}
          data={roleOptions}
          required
          mb="sm"
          {...form.getInputProps('role')}
        />

        {showScopes && (
          <>
            <MultiSelect
              label={t('userManagement.form.scopeGroups')}
              data={groupOptions}
              placeholder={t('userManagement.form.scopeGroupsPlaceholder')}
              searchable
              clearable
              mb="sm"
              {...form.getInputProps('scope_group_ids')}
            />

            <MultiSelect
              label={t('userManagement.form.scopeProjects')}
              data={projectOptions}
              placeholder={t('userManagement.form.scopeProjectsPlaceholder')}
              searchable
              clearable
              mb="sm"
              {...form.getInputProps('scope_project_ids')}
            />
          </>
        )}

        {isEditing && (
          <>
            <Select
              label={t('userManagement.form.linkedPerson')}
              description={t('userManagement.form.linkedPersonHelp')}
              data={personOptions}
              placeholder={t('userManagement.form.linkedPersonPlaceholder')}
              searchable
              clearable
              mb="sm"
              {...form.getInputProps('resource_id')}
            />

            <PasswordInput
              label={t('userManagement.form.resetPassword')}
              description={t('userManagement.form.resetPasswordHelp')}
              placeholder={t('userManagement.form.resetPasswordPlaceholder')}
              mb="sm"
              {...form.getInputProps('newPassword')}
            />
          </>
        )}

        <Group justify="flex-end" mt="lg">
          <Button variant="default" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" loading={loading}>
            {t('common.save')}
          </Button>
        </Group>
      </form>
    </Modal>
  )
}
