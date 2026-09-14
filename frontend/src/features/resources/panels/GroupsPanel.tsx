/**
 * Groups panel: CRUD for resource groups with unified header (title + add + import/export).
 * Accepts a resourceType prop to filter and create groups scoped to personal or infrastructure.
 */

import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ActionIcon, Alert, Button, Group, Loader, Stack, Table, TextInput } from '@mantine/core'
import { DataTable, SectionHeader } from '../../../components/layout'
import { notifications } from '@mantine/notifications'
import { showErrorNotification } from '../../../utils/errorHandling'
import {
  IconAlertCircle,
  IconCheck,
  IconEdit,
  IconPlus,
  IconTrash,
  IconX,
} from '@tabler/icons-react'
import { useTranslation } from '../../../i18n'
import { queryKeys } from '../../../api/queryClient'
import type { ResourceGroup } from '../../../types/resource'
import { createGroup, deleteGroup, getGroups, updateGroup } from '../../../api/resources'

interface GroupsPanelProps {
  /** Scope groups to personal or infrastructure. */
  resourceType: 'personal' | 'infrastructure'
}

export function GroupsPanel({ resourceType }: GroupsPanelProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const [addMode, setAddMode] = useState(false)
  const [addValue, setAddValue] = useState('')

  const [editId, setEditId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')

  const groupsQuery = useQuery({
    queryKey: queryKeys.resources.groups(resourceType),
    queryFn: () => getGroups(resourceType),
  })
  const groups: ResourceGroup[] = groupsQuery.data ?? []
  const loading = groupsQuery.isPending
  const error = groupsQuery.error ? t('groups.loadFailed') : null

  /**
   * A group's NAME is on every resource list, exactly as a site's is.
   *
   * `group_name` is denormalised onto the resource responses, so renaming or deleting a group leaves
   * the people and infrastructure tables showing the old value. The hand-written version reloaded
   * this panel only. The resources invalidation is still a no-op until those screens are converted —
   * see the note on `queryKeys.resources.all` for why it is written now.
   *
   * The digest is NOT invalidated here, and that is a decision rather than an omission: a group is an
   * organisational label, and no finding in the digest is derived from what a group is called.
   */
  const invalidateAfterGroupChange = async () => {
    await Promise.all([queryClient.invalidateQueries({ queryKey: queryKeys.resources.all })])
  }

  const addMutation = useMutation({
    mutationFn: (name: string) => createGroup({ name, resource_type: resourceType }),
    onSuccess: async (_created, name) => {
      setAddValue('')
      setAddMode(false)
      notifications.show({
        title: t('common.created'),
        message: t('groups.created', { name }),
        color: 'green',
      })
      await invalidateAfterGroupChange()
    },
    onError: (err) => showErrorNotification(err, t('common.error'), t('common.genericError')),
  })

  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => updateGroup(id, { name }),
    onSuccess: async () => {
      setEditId(null)
      notifications.show({
        title: t('common.saved'),
        message: t('groups.renamed'),
        color: 'green',
      })
      await invalidateAfterGroupChange()
    },
    onError: (err) => showErrorNotification(err, t('common.error'), t('common.genericError')),
  })

  const deleteMutation = useMutation({
    mutationFn: ({ id }: { id: string; name: string }) => deleteGroup(id),
    onSuccess: async (_deleted, { name }) => {
      notifications.show({
        title: t('common.deleted'),
        message: t('groups.deleted', { name }),
        color: 'green',
      })
      await invalidateAfterGroupChange()
    },
    onError: (err) => showErrorNotification(err, t('common.error'), t('common.genericError')),
  })

  const addSaving = addMutation.isPending
  const editSaving = renameMutation.isPending

  const handleAdd = () => {
    const trimmed = addValue.trim()
    if (!trimmed) return
    addMutation.mutate(trimmed)
  }

  const handleUpdate = () => {
    if (!editId) return
    const trimmed = editValue.trim()
    if (!trimmed) return
    renameMutation.mutate({ id: editId, name: trimmed })
  }

  const handleDelete = (id: string, name: string) => {
    if (!window.confirm(t('groups.deleteConfirm', { name }))) return
    deleteMutation.mutate({ id, name })
  }

  if (loading) return <Loader />
  if (error)
    return (
      <Alert icon={<IconAlertCircle size={16} />} color="red">
        {error}
      </Alert>
    )

  return (
    <Stack gap="md">
      <SectionHeader
        title={t('groups.title')}
        actions={
          !addMode ? (
            <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setAddMode(true)}>
              {t('groups.add')}
            </Button>
          ) : undefined
        }
      />

      {addMode && (
        <Group gap="xs">
          <TextInput
            placeholder={t('groups.placeholder')}
            value={addValue}
            onChange={(e) => setAddValue(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleAdd()
              if (e.key === 'Escape') {
                setAddMode(false)
                setAddValue('')
              }
            }}
            autoFocus
            size="xs"
            style={{ flex: 1 }}
          />
          <ActionIcon
            color="green"
            variant="filled"
            size="sm"
            onClick={handleAdd}
            loading={addSaving}
            aria-label={t('common.save')}
          >
            <IconCheck size={14} />
          </ActionIcon>
          <ActionIcon
            variant="subtle"
            size="sm"
            onClick={() => {
              setAddMode(false)
              setAddValue('')
            }}
            aria-label={t('common.cancel')}
          >
            <IconX size={14} />
          </ActionIcon>
        </Group>
      )}

      <DataTable
        empty={groups.length === 0}
        emptyMessage={t('groups.empty')}
        head={
          <Table.Tr>
            <Table.Th>{t('common.name')}</Table.Th>
            <Table.Th style={{ width: 100 }}>{t('common.actions')}</Table.Th>
          </Table.Tr>
        }
      >
        {groups.map((group) => (
          <Table.Tr key={group.id}>
            <Table.Td>
              {editId === group.id ? (
                <Group gap="xs">
                  <TextInput
                    value={editValue}
                    onChange={(e) => setEditValue(e.currentTarget.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleUpdate()
                      if (e.key === 'Escape') setEditId(null)
                    }}
                    autoFocus
                    size="xs"
                    style={{ flex: 1 }}
                  />
                  <ActionIcon
                    color="green"
                    variant="filled"
                    size="sm"
                    onClick={handleUpdate}
                    loading={editSaving}
                    aria-label={t('common.save')}
                  >
                    <IconCheck size={14} />
                  </ActionIcon>
                  <ActionIcon
                    variant="subtle"
                    size="sm"
                    onClick={() => setEditId(null)}
                    aria-label={t('common.cancel')}
                  >
                    <IconX size={14} />
                  </ActionIcon>
                </Group>
              ) : (
                group.name
              )}
            </Table.Td>
            <Table.Td>
              {editId !== group.id && (
                <Group gap="xs">
                  <ActionIcon
                    variant="subtle"
                    color="blue"
                    size="sm"
                    onClick={() => {
                      setEditId(group.id)
                      setEditValue(group.name)
                    }}
                    aria-label={`${group.name} ${t('common.edit').toLowerCase()}`}
                  >
                    <IconEdit size={14} />
                  </ActionIcon>
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    size="sm"
                    data-testid={`group-delete-${group.id}`}
                    onClick={() => handleDelete(group.id, group.name)}
                    aria-label={`${group.name} ${t('common.delete').toLowerCase()}`}
                  >
                    <IconTrash size={14} />
                  </ActionIcon>
                </Group>
              )}
            </Table.Td>
          </Table.Tr>
        ))}
      </DataTable>
    </Stack>
  )
}
