/**
 * Folder tree for grouping projects. Optional throughout.
 *
 * Folders are a navigation aid, not a planning object: they hold no dates and no work,
 * so deleting one only unfiles what was inside it (ADR-008). The delete confirmation
 * says so explicitly, because "delete folder" reads alarming when the user has a
 * quarter's planning filed under it.
 */

import { useMemo, useState } from 'react'
import {
  ActionIcon,
  Box,
  Button,
  Group,
  Modal,
  NumberInput,
  Select,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core'
import {
  IconChevronDown,
  IconChevronRight,
  IconFolder,
  IconPencil,
  IconPlus,
  IconTrash,
} from '@tabler/icons-react'
import type { ProjectFolder } from '../../types/project'
import { useTranslation } from '../../i18n'
import { useCustomerOptions } from './useCustomerOptions'

interface FolderTreeProps {
  folders: ProjectFolder[]
  /** How many projects sit directly in each folder, keyed by folder id. */
  projectCounts: Record<string, number>
  selectedId: string | 'unfiled' | null
  onSelect: (id: string | 'unfiled' | null) => void
  onCreate: (
    name: string,
    parentId: string | null,
    position: number,
    externalRef: string | null,
    customerId: string | null,
  ) => Promise<void>
  onUpdate: (
    id: string,
    patch: {
      name?: string
      parent_id?: string | null
      position?: number
      external_ref?: string | null
      customer_id?: string | null
    },
  ) => Promise<void>
  onDelete: (id: string) => Promise<void>
  busy?: boolean
}

interface FormState {
  mode: 'create' | 'edit'
  id?: string
  name: string
  parentId: string | null
  position: number
  /** The folder's own identifier — an order number where a folder is an order. */
  externalRef: string
  /** The customer for everything in this folder, inherited by projects and sub-folders. */
  customerId: string | null
}

/** Children of one folder, ordered the way the backend orders them. */
function childrenOf(folders: ProjectFolder[], parentId: string | null): ProjectFolder[] {
  return folders
    .filter((f) => f.parent_id === parentId)
    .sort((a, b) => a.position - b.position || a.name.localeCompare(b.name))
}

/**
 * Ids of every folder below the given one.
 *
 * Used to stop the parent picker offering a folder its own subtree, which the backend
 * would reject anyway — but a form that offers an option and then fails is worse than
 * one that does not offer it.
 */
function descendantIds(folders: ProjectFolder[], id: string): Set<string> {
  const out = new Set<string>()
  const queue = [id]
  while (queue.length > 0) {
    const current = queue.shift() as string
    for (const child of folders.filter((f) => f.parent_id === current)) {
      if (out.has(child.id)) continue
      out.add(child.id)
      queue.push(child.id)
    }
  }
  return out
}

export function FolderTree({
  folders,
  projectCounts,
  selectedId,
  onSelect,
  onCreate,
  onUpdate,
  onDelete,
  busy,
}: FolderTreeProps) {
  // Loaded here rather than passed in: the folder dialog is the primary place a customer gets
  // assigned, and threading the list through every caller would make adding the field elsewhere
  // harder than it needs to be.
  const customerOptions = useCustomerOptions()
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [form, setForm] = useState<FormState | null>(null)
  const [pendingDelete, setPendingDelete] = useState<ProjectFolder | null>(null)
  const [nameError, setNameError] = useState<string | null>(null)

  const parentOptions = useMemo(() => {
    // Editing: a folder may not move into itself or its own subtree.
    const excluded =
      form?.mode === 'edit' && form.id ? descendantIds(folders, form.id) : new Set<string>()
    if (form?.mode === 'edit' && form.id) excluded.add(form.id)
    return folders.filter((f) => !excluded.has(f.id)).map((f) => ({ value: f.id, label: f.name }))
  }, [folders, form])

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const submit = async () => {
    if (!form) return
    if (!form.name.trim()) {
      setNameError(t('folders.nameRequired'))
      return
    }
    setNameError(null)
    // The dialog closes only if the write SUCCEEDED. Previously the panel's handler swallowed its own
    // error, so this await always resolved and the dialog closed on a failed create too — taking the
    // user's typed input with it and leaving a notification about a folder that does not exist. The
    // panel now hands back a rejecting promise, so a failure keeps the form open with its values.
    try {
      if (form.mode === 'create') {
        await onCreate(
          form.name.trim(),
          form.parentId,
          form.position,
          form.externalRef.trim() || null,
          form.customerId,
        )
      } else if (form.id) {
        await onUpdate(form.id, {
          name: form.name.trim(),
          parent_id: form.parentId,
          position: form.position,
          external_ref: form.externalRef.trim() || null,
          customer_id: form.customerId,
        })
      }
    } catch {
      // Already reported by the panel's mutation. Keeping the dialog open IS the handling here.
      return
    }
    setForm(null)
  }

  const renderNode = (folder: ProjectFolder, depth: number) => {
    const children = childrenOf(folders, folder.id)
    const isOpen = expanded.has(folder.id)
    const count = projectCounts[folder.id] ?? 0

    return (
      <Box key={folder.id}>
        <Group
          gap="xs"
          wrap="nowrap"
          px="xs"
          py={4}
          style={{
            paddingLeft: 8 + depth * 18,
            borderRadius: 4,
            cursor: 'pointer',
            background: selectedId === folder.id ? 'var(--mantine-color-blue-light)' : undefined,
          }}
          onClick={() => onSelect(folder.id)}
        >
          {children.length > 0 ? (
            <ActionIcon
              variant="subtle"
              size="sm"
              aria-label={isOpen ? t('folders.collapse') : t('folders.expand')}
              onClick={(event) => {
                event.stopPropagation()
                toggle(folder.id)
              }}
            >
              {isOpen ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
            </ActionIcon>
          ) : (
            <Box w={26} />
          )}
          <IconFolder size={16} />
          <Text size="sm" style={{ flex: 1 }} truncate>
            {folder.name}
          </Text>
          <Text size="xs" c="dimmed">
            {count}
          </Text>
          <Tooltip label={t('folders.addSubfolder')}>
            <ActionIcon
              variant="subtle"
              size="sm"
              aria-label={t('folders.addSubfolder')}
              onClick={(event) => {
                event.stopPropagation()
                setForm({
                  mode: 'create',
                  name: '',
                  parentId: folder.id,
                  position: 0,
                  externalRef: '',
                  customerId: null,
                })
              }}
            >
              <IconPlus size={14} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label={t('common.edit')}>
            <ActionIcon
              variant="subtle"
              size="sm"
              aria-label={t('common.edit')}
              onClick={(event) => {
                event.stopPropagation()
                setForm({
                  mode: 'edit',
                  id: folder.id,
                  name: folder.name,
                  parentId: folder.parent_id,
                  position: folder.position,
                  externalRef: folder.external_ref ?? '',
                  customerId: folder.customer_id ?? null,
                })
              }}
            >
              <IconPencil size={14} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label={t('common.delete')}>
            <ActionIcon
              variant="subtle"
              color="red"
              size="sm"
              aria-label={t('common.delete')}
              onClick={(event) => {
                event.stopPropagation()
                setPendingDelete(folder)
              }}
            >
              <IconTrash size={14} />
            </ActionIcon>
          </Tooltip>
        </Group>
        {isOpen && children.map((child) => renderNode(child, depth + 1))}
      </Box>
    )
  }

  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Text fw={500} size="sm">
          {t('folders.title')}
        </Text>
        <Button
          size="xs"
          variant="light"
          leftSection={<IconPlus size={14} />}
          onClick={() =>
            setForm({
              mode: 'create',
              name: '',
              parentId: null,
              position: 0,
              externalRef: '',
              customerId: null,
            })
          }
        >
          {t('folders.add')}
        </Button>
      </Group>

      <Group
        gap="xs"
        px="xs"
        py={4}
        style={{
          borderRadius: 4,
          cursor: 'pointer',
          background: selectedId === null ? 'var(--mantine-color-blue-light)' : undefined,
        }}
        onClick={() => onSelect(null)}
      >
        <Box w={26} />
        <Text size="sm">{t('folders.all')}</Text>
      </Group>

      {folders.length === 0 ? (
        <Text size="xs" c="dimmed" px="xs">
          {t('folders.empty')}
        </Text>
      ) : (
        childrenOf(folders, null).map((folder) => renderNode(folder, 0))
      )}

      <Group
        gap="xs"
        px="xs"
        py={4}
        style={{
          borderRadius: 4,
          cursor: 'pointer',
          background: selectedId === 'unfiled' ? 'var(--mantine-color-blue-light)' : undefined,
        }}
        onClick={() => onSelect('unfiled')}
      >
        <Box w={26} />
        <Text size="sm" c="dimmed">
          {t('folders.unfiled')}
        </Text>
      </Group>

      <Modal
        opened={form !== null}
        onClose={() => setForm(null)}
        title={form?.mode === 'edit' ? t('folders.editTitle') : t('folders.createTitle')}
      >
        <Stack gap="md">
          <TextInput
            label={t('common.name')}
            required
            value={form?.name ?? ''}
            error={nameError}
            onChange={(event) =>
              setForm((prev) => (prev ? { ...prev, name: event.currentTarget.value } : prev))
            }
          />
          <Select
            label={t('folders.parent')}
            description={t('folders.parentDesc')}
            placeholder={t('folders.topLevel')}
            clearable
            data={parentOptions}
            value={form?.parentId ?? null}
            onChange={(value) => setForm((prev) => (prev ? { ...prev, parentId: value } : prev))}
          />
          <Select
            label={t('projectFolder.customer')}
            description={t('projectFolder.customerDesc')}
            placeholder={t('projectForm.customerNone')}
            data={customerOptions}
            clearable
            searchable
            value={form?.customerId ?? null}
            onChange={(value) => setForm((prev) => (prev ? { ...prev, customerId: value } : prev))}
          />
          <TextInput
            label={t('folders.externalRef')}
            description={t('folders.externalRefDesc')}
            maxLength={128}
            value={form?.externalRef ?? ''}
            onChange={(event) =>
              setForm((prev) => (prev ? { ...prev, externalRef: event.currentTarget.value } : prev))
            }
          />
          <NumberInput
            label={t('folders.position')}
            description={t('folders.positionDesc')}
            min={0}
            allowDecimal={false}
            allowNegative={false}
            value={form?.position ?? 0}
            onChange={(value) =>
              setForm((prev) =>
                prev ? { ...prev, position: typeof value === 'number' ? value : 0 } : prev,
              )
            }
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setForm(null)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={submit} loading={busy}>
              {t('common.save')}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        title={t('folders.deleteTitle')}
      >
        <Stack gap="md">
          {/* Spelled out because "delete folder" reads alarming when a quarter's
              planning is filed under it. Nothing inside is deleted. */}
          <Text size="sm">{t('folders.deleteConfirm', { name: pendingDelete?.name ?? '' })}</Text>
          <Text size="sm" c="dimmed">
            {t('folders.deleteKeepsContents')}
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setPendingDelete(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              color="red"
              loading={busy}
              onClick={async () => {
                if (pendingDelete) await onDelete(pendingDelete.id)
                setPendingDelete(null)
              }}
            >
              {t('common.delete')}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
