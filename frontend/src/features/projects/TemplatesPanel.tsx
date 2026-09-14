/**
 * Templates panel: Self-contained CRUD for work package templates with inline requirements.
 *
 * Renders a FilterBar with search input and "New Template" button, followed by a
 * DataTable of templates. Supports client-side search filtering by template name
 * (case-insensitive). Edit button opens a modal with name, description, and
 * requirements management via the shared RequirementsEditor component.
 */

import { useEffect, useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ActionIcon,
  Badge,
  Button,
  Divider,
  Group,
  Modal,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
} from '@mantine/core'
import { DataTable, FilterBar } from '../../components/layout'
import { notifications } from '@mantine/notifications'
import { showErrorNotification } from '../../utils/errorHandling'
import { IconEdit, IconPlus, IconSearch, IconTrash } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import apiClient from '../../api/client'
import {
  getTemplate,
  addTemplateRequirement,
  removeTemplateRequirement,
  type TemplateListItem,
  type TemplateRequirement,
} from '../../api/templates'
import { RequirementsEditor } from '../../components/RequirementsEditor'

export function TemplatesPanel() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const templatesQuery = useQuery({
    queryKey: queryKeys.templates.list(),
    queryFn: async () => {
      const res = await apiClient.get<{ items: TemplateListItem[]; total: number }>(
        '/api/templates',
      )
      return res.data.items
    },
  })
  const templates: TemplateListItem[] = templatesQuery.data ?? []
  const loading = templatesQuery.isPending

  useEffect(() => {
    if (templatesQuery.error) {
      showErrorNotification(templatesQuery.error, t('common.error'), t('common.loadFailed'))
    }
  }, [templatesQuery.error, t])

  const filteredTemplates = useMemo(() => {
    if (!search.trim()) return templates
    const query = search.trim().toLowerCase()
    return templates.filter((tpl) => tpl.name.toLowerCase().includes(query))
  }, [templates, search])

  const openCreate = () => {
    setEditingId(null)
    setName('')
    setDescription('')
    // No requirements to clear: editingId=null disables the detail query, so the list is empty
    // by construction rather than by remembering to reset it.
    setFormOpen(true)
  }

  const openEdit = (tpl: TemplateListItem) => {
    setEditingId(tpl.id)
    setName(tpl.name)
    setDescription(tpl.description || '')
    setFormOpen(true)
  }

  /**
   * The open template's requirements. THREE PLACES fetched this — opening the editor, and after each of
   * the two requirement writes — each with its own `setRequirements(detail.requirements)`. All three
   * were the same read, so all three are one query now, and the writes invalidate instead of re-reading.
   *
   * Still degrades to an empty list on failure: the editor is usable without it, and the requirements
   * shown are what the user is about to change anyway.
   */
  const detailQuery = useQuery({
    queryKey: queryKeys.templates.detail(editingId ?? 'none'),
    queryFn: () => getTemplate(editingId!),
    enabled: Boolean(editingId),
  })
  const requirements: TemplateRequirement[] = detailQuery.data?.requirements ?? []

  const invalidateTemplates = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.templates.all })

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = { name: name.trim(), description: description.trim() || null }
      return editingId
        ? apiClient.put(`/api/templates/${editingId}`, payload)
        : apiClient.post('/api/templates', payload)
    },
    onSuccess: async () => {
      notifications.show({
        title: editingId ? t('common.saved') : t('common.created'),
        message: editingId ? t('templates.updated') : t('templates.created'),
        color: 'green',
      })
      setFormOpen(false)
      await invalidateTemplates()
    },
    onError: (error) => showErrorNotification(error, t('common.error'), t('common.genericError')),
  })

  const saving = saveMutation.isPending

  const handleSave = () => {
    if (!name.trim()) return
    saveMutation.mutate()
  }

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.delete(`/api/templates/${id}`),
    onSuccess: async () => {
      notifications.show({
        title: t('common.deleted'),
        message: t('templates.deleted'),
        color: 'green',
      })
      await invalidateTemplates()
    },
    onError: (error) => showErrorNotification(error, t('common.error'), t('common.genericError')),
  })

  const handleDelete = (id: string, tplName: string) => {
    if (!window.confirm(t('templates.deleteConfirm', { name: tplName }))) return
    deleteMutation.mutate(id)
  }

  const addReqMutation = useMutation({
    mutationFn: (data: { skill_id: string; skill_attribute_id: string | null; quantity: number }) =>
      addTemplateRequirement(editingId!, data),
    onSuccess: () => invalidateTemplates(),
    onError: (error) => showErrorNotification(error, t('common.error'), t('common.genericError')),
  })

  const handleAddReq = (data: {
    skill_id: string
    skill_attribute_id: string | null
    quantity: number
  }) => {
    if (!editingId) return Promise.resolve()
    return addReqMutation.mutateAsync(data).then(() => undefined)
  }

  const removeReqMutation = useMutation({
    mutationFn: (req: TemplateRequirement) => removeTemplateRequirement(editingId!, req.id),
    onSuccess: () => invalidateTemplates(),
    onError: (error) => showErrorNotification(error, t('common.error'), t('common.genericError')),
  })

  const handleRemoveReq = (req: TemplateRequirement) => {
    if (!editingId) return Promise.resolve()
    return removeReqMutation.mutateAsync(req).then(() => undefined)
  }

  const reqLoading =
    addReqMutation.isPending || removeReqMutation.isPending || detailQuery.isFetching

  return (
    <>
      <FilterBar>
        <TextInput
          placeholder={t('templates.searchPlaceholder')}
          leftSection={<IconSearch size={14} />}
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          style={{ minWidth: 260 }}
          aria-label={t('templates.searchPlaceholder')}
        />
        <Button leftSection={<IconPlus size={16} />} onClick={openCreate} ml="auto">
          {t('templates.add')}
        </Button>
      </FilterBar>

      <DataTable
        loading={loading}
        empty={filteredTemplates.length === 0}
        emptyMessage={t('templates.empty')}
        head={
          <Table.Tr>
            <Table.Th>{t('common.name')}</Table.Th>
            <Table.Th>{t('templates.description')}</Table.Th>
            <Table.Th>{t('templates.requirements')}</Table.Th>
            <Table.Th style={{ width: 80 }}>{t('common.actions')}</Table.Th>
          </Table.Tr>
        }
      >
        {filteredTemplates.map((tpl) => (
          <Table.Tr key={tpl.id}>
            <Table.Td fw={500}>{tpl.name}</Table.Td>
            <Table.Td>
              <Text size="sm" c="dimmed" lineClamp={1}>
                {tpl.description || '—'}
              </Text>
            </Table.Td>
            <Table.Td>
              <Badge size="sm" variant="light">
                {tpl.requirement_count}
              </Badge>
            </Table.Td>
            <Table.Td>
              <Group gap="xs">
                <ActionIcon
                  variant="subtle"
                  color="blue"
                  size="sm"
                  onClick={() => openEdit(tpl)}
                  aria-label={t('common.edit')}
                >
                  <IconEdit size={14} />
                </ActionIcon>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  size="sm"
                  onClick={() => handleDelete(tpl.id, tpl.name)}
                  aria-label={t('common.delete')}
                >
                  <IconTrash size={14} />
                </ActionIcon>
              </Group>
            </Table.Td>
          </Table.Tr>
        ))}
      </DataTable>

      {/* Create/Edit Modal with inline requirements */}
      <Modal
        opened={formOpen}
        onClose={() => setFormOpen(false)}
        title={editingId ? t('templates.edit') : t('templates.add')}
        size="lg"
      >
        <Stack gap="md">
          <TextInput
            label={t('common.name')}
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            required
          />
          <Textarea
            label={t('templates.description')}
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
            rows={2}
          />

          {/* Requirements section (only when editing existing template) */}
          {editingId && (
            <>
              <Divider />
              <Text fw={600} size="sm">
                {t('requirements.title')}
              </Text>
              <RequirementsEditor
                requirements={requirements}
                onAdd={handleAddReq}
                onRemove={handleRemoveReq}
                loading={reqLoading}
              />
            </>
          )}

          <Group justify="flex-end" mt="sm">
            <Button variant="default" onClick={() => setFormOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={handleSave} loading={saving}>
              {t('common.save')}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  )
}
