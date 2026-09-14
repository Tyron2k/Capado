/**
 * Admin-only user management page at /admin/users.
 * Displays a table of all users with create, edit, and deactivate actions.
 */

import { useEffect, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ActionIcon, Badge, Button, Group, Modal, Pagination, Table, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { showErrorNotification } from '../../utils/errorHandling'
import { IconEdit, IconPlus, IconTrash, IconUserOff } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { DataTable, PageLayout } from '../../components/layout'
import {
  getUsers,
  createUser,
  updateUser,
  deleteUser,
  permanentlyDeleteUser,
  type User,
  type UserCreateData,
  type UserUpdateData,
} from '../../api/users'
import { UserFormModal } from './UserFormModal'

const PAGE_SIZE = 50

/**
 * Renders the user management page with a paginated table and CRUD modals.
 */
export function UserManagementPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [deactivateUser, setDeactivateUser] = useState<User | null>(null)
  const [permanentDeleteUser, setPermanentDeleteUser] = useState<User | null>(null)

  const usersQuery = useQuery({
    queryKey: queryKeys.admin.users((page - 1) * PAGE_SIZE, PAGE_SIZE),
    queryFn: () => getUsers((page - 1) * PAGE_SIZE, PAGE_SIZE),
  })
  const users: User[] = usersQuery.data?.items ?? []
  const total = usersQuery.data?.total ?? 0
  const loading = usersQuery.isPending

  useEffect(() => {
    if (usersQuery.error) {
      showErrorNotification(usersQuery.error, t('common.error'), t('userManagement.loadFailed'))
    }
  }, [usersQuery.error, t])

  /**
   * A USER IS A LOGIN, NOT A PARTICIPANT IN THE PLAN.
   *
   * This is the one screen in the product where the coarse prefix is the WHOLE invalidation. Creating,
   * deactivating or deleting a user changes who may sign in and what they may edit; it changes nothing
   * about who is assigned to what, because Capado plans PEOPLE as resources and those are a separate
   * entity from the accounts that log in — deliberately, since most of the workforce here has no login
   * at all. So no `resources`, no `conflicts`, no `digest`.
   *
   * `admin.all` rather than the current page's key: a deactivation can move a user between pages, so
   * refreshing only the page you are looking at would leave the neighbouring pages wrong.
   */
  const invalidateUsers = () => queryClient.invalidateQueries({ queryKey: queryKeys.admin.all })

  const handleCreate = () => {
    setEditingUser(null)
    setModalOpen(true)
  }

  const handleEdit = (user: User) => {
    setEditingUser(user)
    setModalOpen(true)
  }

  const saveMutation = useMutation({
    mutationFn: (data: UserCreateData | UserUpdateData) =>
      editingUser
        ? updateUser(editingUser.id, data as UserUpdateData)
        : createUser(data as UserCreateData),
    onSuccess: async () => {
      notifications.show({
        title: t('common.success'),
        message: editingUser ? t('userManagement.userUpdated') : t('userManagement.userCreated'),
        color: 'green',
      })
      setModalOpen(false)
      setEditingUser(null)
      await invalidateUsers()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })
  const saving = saveMutation.isPending

  /**
   * Returns a promise because the modal's prop type awaits it. It RESOLVES on failure rather than
   * rejecting: the modal does not catch, so a rejection here would surface as an unhandled promise
   * rejection rather than as anything the user can see. What keeps the form open on a failed save is
   * that `setModalOpen(false)` lives in `onSuccess` and nowhere else — so the values survive, and the
   * error arrives as the notification the mutation's `onError` shows.
   */
  const handleFormSubmit = (data: UserCreateData | UserUpdateData) =>
    saveMutation.mutateAsync(data).then(
      () => undefined,
      () => undefined,
    )

  const deactivateMutation = useMutation({
    mutationFn: (id: string) => deleteUser(id),
    onSuccess: async () => {
      notifications.show({
        title: t('common.success'),
        message: t('userManagement.userDeactivated'),
        color: 'green',
      })
      setDeactivateUser(null)
      await invalidateUsers()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const handleDeactivate = () => {
    if (!deactivateUser) return
    deactivateMutation.mutate(deactivateUser.id)
  }

  const permanentDeleteMutation = useMutation({
    mutationFn: (id: string) => permanentlyDeleteUser(id),
    onSuccess: async () => {
      notifications.show({
        title: t('common.success'),
        message: t('userManagement.userDeleted'),
        color: 'green',
      })
      setPermanentDeleteUser(null)
      await invalidateUsers()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const handlePermanentDelete = () => {
    if (!permanentDeleteUser) return
    permanentDeleteMutation.mutate(permanentDeleteUser.id)
  }

  const formatScopes = (user: User): string => {
    if (user.role !== 'editor') return '—'
    const parts: string[] = []
    if (user.scope_group_ids?.length) parts.push(`${user.scope_group_ids.length} groups`)
    if (user.scope_project_ids?.length) parts.push(`${user.scope_project_ids.length} proj`)
    return parts.length > 0 ? parts.join(', ') : '—'
  }

  const roleBadgeColor = (role: string): string => {
    switch (role) {
      case 'admin':
        return 'red'
      case 'editor':
        return 'blue'
      default:
        return 'gray'
    }
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)

  const rows = users.map((user) => (
    <Table.Tr key={user.id}>
      <Table.Td>{user.name}</Table.Td>
      <Table.Td>{user.email}</Table.Td>
      <Table.Td>
        <Badge color={roleBadgeColor(user.role)} variant="light">
          {user.role}
        </Badge>
      </Table.Td>
      <Table.Td>{formatScopes(user)}</Table.Td>
      <Table.Td>
        <Badge color={user.is_active ? 'green' : 'gray'} variant="light">
          {user.is_active ? t('userManagement.active') : t('userManagement.inactive')}
        </Badge>
      </Table.Td>
      <Table.Td>
        <Group gap="xs">
          <ActionIcon
            variant="subtle"
            color="blue"
            onClick={() => handleEdit(user)}
            aria-label={t('userManagement.editUser')}
          >
            <IconEdit size={18} />
          </ActionIcon>
          {user.is_active && (
            <ActionIcon
              variant="subtle"
              color="red"
              onClick={() => setDeactivateUser(user)}
              aria-label={t('common.deactivate')}
            >
              <IconUserOff size={18} />
            </ActionIcon>
          )}
          {!user.is_active && (
            <ActionIcon
              variant="subtle"
              color="red"
              onClick={() => setPermanentDeleteUser(user)}
              aria-label={t('userManagement.permanentDelete')}
            >
              <IconTrash size={18} />
            </ActionIcon>
          )}
        </Group>
      </Table.Td>
    </Table.Tr>
  ))

  return (
    <PageLayout
      title={t('userManagement.title')}
      headerActions={
        <Button leftSection={<IconPlus size={18} />} onClick={handleCreate}>
          {t('userManagement.createUser')}
        </Button>
      }
    >
      <DataTable
        loading={loading}
        empty={users.length === 0}
        emptyMessage={t('userManagement.noUsers')}
        head={
          <Table.Tr>
            <Table.Th>{t('common.name')}</Table.Th>
            <Table.Th>{t('userManagement.form.email')}</Table.Th>
            <Table.Th>{t('userManagement.form.role')}</Table.Th>
            <Table.Th>{t('userManagement.scopes')}</Table.Th>
            <Table.Th>{t('common.status')}</Table.Th>
            <Table.Th>{t('common.actions')}</Table.Th>
          </Table.Tr>
        }
      >
        {rows}
      </DataTable>

      {!loading && totalPages > 1 && (
        <Group justify="center" mt="md">
          <Pagination total={totalPages} value={page} onChange={setPage} />
        </Group>
      )}

      <UserFormModal
        opened={modalOpen}
        onClose={() => {
          setModalOpen(false)
          setEditingUser(null)
        }}
        onSubmit={handleFormSubmit}
        user={editingUser}
        loading={saving}
      />

      {/* Deactivate confirmation modal */}
      <Modal
        opened={deactivateUser !== null}
        onClose={() => setDeactivateUser(null)}
        title={t('userManagement.deactivateUser')}
        size="sm"
      >
        <Text mb="lg">
          {t('userManagement.deactivateConfirm', { name: deactivateUser?.name ?? '' })}
        </Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={() => setDeactivateUser(null)}>
            {t('common.cancel')}
          </Button>
          <Button color="red" onClick={handleDeactivate}>
            {t('common.deactivate')}
          </Button>
        </Group>
      </Modal>

      {/* Permanent delete confirmation modal */}
      <Modal
        opened={permanentDeleteUser !== null}
        onClose={() => setPermanentDeleteUser(null)}
        title={t('userManagement.permanentDelete')}
        size="sm"
      >
        <Text mb="lg">
          {t('userManagement.permanentDeleteConfirm', { name: permanentDeleteUser?.name ?? '' })}
        </Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={() => setPermanentDeleteUser(null)}>
            {t('common.cancel')}
          </Button>
          <Button color="red" onClick={handlePermanentDelete}>
            {t('userManagement.permanentDeleteAction')}
          </Button>
        </Group>
      </Modal>
    </PageLayout>
  )
}
