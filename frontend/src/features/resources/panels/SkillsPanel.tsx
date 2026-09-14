/**
 * Skills panel with unified header (title + add + import/export).
 * Manages skills and their attributes. Shared between personnel and infrastructure.
 */

import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Collapse,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core'
import { SectionHeader } from '../../../components/layout'
import { notifications } from '@mantine/notifications'
import { showErrorNotification } from '../../../utils/errorHandling'
import {
  IconAlertCircle,
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconEdit,
  IconPlus,
  IconTrash,
  IconX,
} from '@tabler/icons-react'
import { useTranslation } from '../../../i18n'
import { queryKeys } from '../../../api/queryClient'
import type { SkillWithAttributes } from '../../../types/skill'
import {
  createSkill,
  createSkillAttribute,
  deleteSkill,
  deleteSkillAttribute,
  getSkillsWithAttributes,
  updateSkill,
  updateSkillAttribute,
} from '../../../api/skills'

interface SkillsPanelProps {
  resourceType?: 'personal' | 'infrastructure'
}

export function SkillsPanel({ resourceType = 'personal' }: SkillsPanelProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [expandedSkills, setExpandedSkills] = useState<Set<string>>(new Set())

  // Add skill
  const [addSkillMode, setAddSkillMode] = useState(false)
  const [addSkillValue, setAddSkillValue] = useState('')

  // Edit skill
  const [editSkillId, setEditSkillId] = useState<string | null>(null)
  const [editSkillValue, setEditSkillValue] = useState('')

  // Add attribute
  const [addAttrSkillId, setAddAttrSkillId] = useState<string | null>(null)
  const [addAttrValue, setAddAttrValue] = useState('')

  // Edit attribute
  const [editAttrId, setEditAttrId] = useState<string | null>(null)
  const [editAttrValue, setEditAttrValue] = useState('')

  const skillsQuery = useQuery({
    queryKey: queryKeys.skills.withAttributes(resourceType),
    queryFn: () => getSkillsWithAttributes(resourceType),
  })
  const skills: SkillWithAttributes[] = skillsQuery.data ?? []
  const loading = skillsQuery.isPending
  // Reported INLINE rather than as a notification: without the catalogue this panel has nothing to
  // show, so the message belongs where the list would be.
  const error = skillsQuery.error ? t('skills.loadFailed') : null

  /**
   * THE SKILL CATALOGUE IS THE ONE PIECE OF MASTER DATA THAT REACHES INTO THE PLAN.
   *
   * Everything else in this migration divides cleanly: a customer or a folder is a label, an
   * assignment or a date is a commitment. A skill is neither and both. It is edited here as master
   * data, but a requirement points at it and a qualification points at it, and whether an assignment
   * is sound is decided by comparing those two THROUGH this catalogue. Deleting an attribute does not
   * touch a single assignment, yet it can turn a covered requirement into an uncovered one.
   *
   * So all six writes here declare the same five things untrue. `skills` for this panel, `resources`
   * for the qualification lists and the matrix, `projects` for the requirement editors that offer
   * these names, `conflicts` because a skill mismatch is computed from them, and `digest` because an
   * uncovered requirement is exactly the kind of finding it reports.
   *
   * Not `assignments`: the assignments themselves are unchanged. What changed is whether they are
   * correct, and that is what `conflicts` and `digest` are for.
   */
  const invalidateAfterSkillChange = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.skills.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
    ])

  const reportSkillError = (err: unknown) =>
    showErrorNotification(err, t('common.error'), t('common.genericError'))

  const toggleSkill = (id: string) => {
    setExpandedSkills((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const addSkillMutation = useMutation({
    mutationFn: (name: string) => createSkill({ name, resource_type: resourceType }),
    onSuccess: async (_result, name) => {
      setAddSkillValue('')
      setAddSkillMode(false)
      notifications.show({
        title: t('common.created'),
        message: `Skill "${name}" ${t('skills.created')}`,
        color: 'green',
      })
      await invalidateAfterSkillChange()
    },
    onError: reportSkillError,
  })
  const addSkillSaving = addSkillMutation.isPending

  const handleAddSkill = () => {
    const trimmed = addSkillValue.trim()
    if (!trimmed) return
    addSkillMutation.mutate(trimmed)
  }

  const updateSkillMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => updateSkill(id, { name }),
    onSuccess: async () => {
      setEditSkillId(null)
      notifications.show({ title: t('common.saved'), message: t('skills.renamed'), color: 'green' })
      await invalidateAfterSkillChange()
    },
    onError: reportSkillError,
  })
  const editSkillSaving = updateSkillMutation.isPending

  const handleUpdateSkill = () => {
    if (!editSkillId) return
    const trimmed = editSkillValue.trim()
    if (!trimmed) return
    updateSkillMutation.mutate({ id: editSkillId, name: trimmed })
  }

  const deleteSkillMutation = useMutation({
    mutationFn: ({ id }: { id: string; name: string }) => deleteSkill(id),
    onSuccess: async (_result, { name }) => {
      notifications.show({
        title: t('common.deleted'),
        message: `Skill "${name}" ${t('skills.deleted')}`,
        color: 'green',
      })
      await invalidateAfterSkillChange()
    },
    onError: reportSkillError,
  })

  const handleDeleteSkill = (id: string, name: string) => {
    if (!window.confirm(t('skills.deleteConfirm', { name }))) return
    deleteSkillMutation.mutate({ id, name })
  }

  const addAttrMutation = useMutation({
    mutationFn: ({ skillId, name }: { skillId: string; name: string }) =>
      createSkillAttribute(skillId, { name }),
    onSuccess: async (_result, { name }) => {
      setAddAttrValue('')
      setAddAttrSkillId(null)
      notifications.show({
        title: t('common.created'),
        message: `"${name}" ${t('skills.attributeCreated')}`,
        color: 'green',
      })
      await invalidateAfterSkillChange()
    },
    onError: reportSkillError,
  })
  const addAttrSaving = addAttrMutation.isPending

  const handleAddAttribute = (skillId: string) => {
    const trimmed = addAttrValue.trim()
    if (!trimmed) return
    addAttrMutation.mutate({ skillId, name: trimmed })
  }

  const updateAttrMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => updateSkillAttribute(id, { name }),
    onSuccess: async () => {
      setEditAttrId(null)
      notifications.show({
        title: t('common.saved'),
        message: t('skills.attributeRenamed'),
        color: 'green',
      })
      await invalidateAfterSkillChange()
    },
    onError: reportSkillError,
  })
  const editAttrSaving = updateAttrMutation.isPending

  const handleUpdateAttribute = () => {
    if (!editAttrId) return
    const trimmed = editAttrValue.trim()
    if (!trimmed) return
    updateAttrMutation.mutate({ id: editAttrId, name: trimmed })
  }

  const deleteAttrMutation = useMutation({
    mutationFn: ({ id }: { id: string; name: string }) => deleteSkillAttribute(id),
    onSuccess: async (_result, { name }) => {
      notifications.show({
        title: t('common.deleted'),
        message: `"${name}" ${t('skills.attributeDeleted')}`,
        color: 'green',
      })
      await invalidateAfterSkillChange()
    },
    onError: reportSkillError,
  })

  const handleDeleteAttribute = (id: string, name: string) => {
    if (!window.confirm(t('skills.deleteAttributeConfirm', { name }))) return
    deleteAttrMutation.mutate({ id, name })
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
        title={t('skills.title')}
        actions={
          !addSkillMode ? (
            <Button
              size="xs"
              leftSection={<IconPlus size={14} />}
              onClick={() => setAddSkillMode(true)}
            >
              {t('skills.addSkill')}
            </Button>
          ) : undefined
        }
      />

      {addSkillMode && (
        <Group gap="xs">
          <TextInput
            placeholder={t('skills.newSkillPlaceholder')}
            value={addSkillValue}
            onChange={(e) => setAddSkillValue(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleAddSkill()
              if (e.key === 'Escape') {
                setAddSkillMode(false)
                setAddSkillValue('')
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
            onClick={handleAddSkill}
            loading={addSkillSaving}
            aria-label={t('common.save')}
          >
            <IconCheck size={14} />
          </ActionIcon>
          <ActionIcon
            variant="subtle"
            size="sm"
            onClick={() => {
              setAddSkillMode(false)
              setAddSkillValue('')
            }}
            aria-label={t('common.cancel')}
          >
            <IconX size={14} />
          </ActionIcon>
        </Group>
      )}

      {skills.length === 0 ? (
        <Text c="dimmed">{t('skills.noSkills')}</Text>
      ) : (
        <Stack gap="xs">
          {skills.map((skill) => {
            const isExpanded = expandedSkills.has(skill.id)
            return (
              <div key={skill.id}>
                <Group
                  gap="xs"
                  py={6}
                  px="xs"
                  style={{
                    borderRadius: 4,
                    backgroundColor:
                      'light-dark(var(--mantine-color-gray-0), var(--mantine-color-dark-6))',
                    cursor: 'pointer',
                  }}
                  onClick={() => toggleSkill(skill.id)}
                  onKeyDown={(e: React.KeyboardEvent) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      toggleSkill(skill.id)
                    }
                  }}
                  tabIndex={0}
                  role="button"
                  aria-expanded={isExpanded}
                  aria-label={skill.name}
                >
                  {isExpanded ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
                  {editSkillId === skill.id ? (
                    <Group gap="xs" style={{ flex: 1 }} onClick={(e) => e.stopPropagation()}>
                      <TextInput
                        value={editSkillValue}
                        onChange={(e) => setEditSkillValue(e.currentTarget.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleUpdateSkill()
                          if (e.key === 'Escape') setEditSkillId(null)
                        }}
                        autoFocus
                        size="xs"
                        style={{ flex: 1 }}
                      />
                      <ActionIcon
                        color="green"
                        variant="filled"
                        size="sm"
                        onClick={handleUpdateSkill}
                        loading={editSkillSaving}
                        aria-label={t('common.save')}
                      >
                        <IconCheck size={14} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        size="sm"
                        onClick={() => setEditSkillId(null)}
                        aria-label={t('common.cancel')}
                      >
                        <IconX size={14} />
                      </ActionIcon>
                    </Group>
                  ) : (
                    <>
                      <Text size="sm" fw={600} style={{ flex: 1 }}>
                        {skill.name}
                      </Text>
                      <Badge size="xs" variant="light">
                        {skill.attributes.length} {t('skills.attributes')}
                      </Badge>
                      <Group gap={4} onClick={(e) => e.stopPropagation()}>
                        <ActionIcon
                          variant="subtle"
                          color="blue"
                          size="sm"
                          onClick={() => {
                            setEditSkillId(skill.id)
                            setEditSkillValue(skill.name)
                          }}
                          aria-label={`${skill.name} ${t('common.edit').toLowerCase()}`}
                        >
                          <IconEdit size={14} />
                        </ActionIcon>
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          size="sm"
                          data-testid={`skill-delete-${skill.id}`}
                          onClick={() => handleDeleteSkill(skill.id, skill.name)}
                          aria-label={`${skill.name} ${t('common.delete').toLowerCase()}`}
                        >
                          <IconTrash size={14} />
                        </ActionIcon>
                      </Group>
                    </>
                  )}
                </Group>

                <Collapse expanded={isExpanded}>
                  <Table striped withTableBorder ml="md" mt="xs">
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>{t('skills.attribute')}</Table.Th>
                        <Table.Th style={{ width: 100 }}>{t('common.actions')}</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {skill.attributes.map((attr) => (
                        <Table.Tr key={attr.id}>
                          <Table.Td>
                            {editAttrId === attr.id ? (
                              <Group gap="xs">
                                <TextInput
                                  value={editAttrValue}
                                  onChange={(e) => setEditAttrValue(e.currentTarget.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') handleUpdateAttribute()
                                    if (e.key === 'Escape') setEditAttrId(null)
                                  }}
                                  autoFocus
                                  size="xs"
                                  style={{ flex: 1 }}
                                />
                                <ActionIcon
                                  color="green"
                                  variant="filled"
                                  size="sm"
                                  onClick={handleUpdateAttribute}
                                  loading={editAttrSaving}
                                  aria-label={t('common.save')}
                                >
                                  <IconCheck size={14} />
                                </ActionIcon>
                                <ActionIcon
                                  variant="subtle"
                                  size="sm"
                                  onClick={() => setEditAttrId(null)}
                                  aria-label={t('common.cancel')}
                                >
                                  <IconX size={14} />
                                </ActionIcon>
                              </Group>
                            ) : (
                              attr.name
                            )}
                          </Table.Td>
                          <Table.Td>
                            {editAttrId !== attr.id && (
                              <Group gap="xs">
                                <ActionIcon
                                  variant="subtle"
                                  color="blue"
                                  size="sm"
                                  onClick={() => {
                                    setEditAttrId(attr.id)
                                    setEditAttrValue(attr.name)
                                  }}
                                  aria-label={`${attr.name} ${t('common.edit').toLowerCase()}`}
                                >
                                  <IconEdit size={14} />
                                </ActionIcon>
                                <ActionIcon
                                  variant="subtle"
                                  color="red"
                                  size="sm"
                                  onClick={() => handleDeleteAttribute(attr.id, attr.name)}
                                  aria-label={`${attr.name} ${t('common.delete').toLowerCase()}`}
                                >
                                  <IconTrash size={14} />
                                </ActionIcon>
                              </Group>
                            )}
                          </Table.Td>
                        </Table.Tr>
                      ))}
                      {skill.attributes.length === 0 && (
                        <Table.Tr>
                          <Table.Td colSpan={2}>
                            <Text size="sm" c="dimmed">
                              {t('skills.noAttributes')}
                            </Text>
                          </Table.Td>
                        </Table.Tr>
                      )}
                    </Table.Tbody>
                  </Table>
                  {addAttrSkillId === skill.id ? (
                    <Group gap="xs" mt="xs" ml="md">
                      <TextInput
                        placeholder={t('skills.newAttributePlaceholder')}
                        value={addAttrValue}
                        onChange={(e) => setAddAttrValue(e.currentTarget.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleAddAttribute(skill.id)
                          if (e.key === 'Escape') {
                            setAddAttrSkillId(null)
                            setAddAttrValue('')
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
                        onClick={() => handleAddAttribute(skill.id)}
                        loading={addAttrSaving}
                        aria-label={t('common.save')}
                      >
                        <IconCheck size={14} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        size="sm"
                        onClick={() => {
                          setAddAttrSkillId(null)
                          setAddAttrValue('')
                        }}
                        aria-label={t('common.cancel')}
                      >
                        <IconX size={14} />
                      </ActionIcon>
                    </Group>
                  ) : (
                    <Button
                      size="xs"
                      variant="subtle"
                      leftSection={<IconPlus size={12} />}
                      mt="xs"
                      ml="md"
                      onClick={() => {
                        setAddAttrSkillId(skill.id)
                        setAddAttrValue('')
                      }}
                    >
                      {t('skills.addAttribute')}
                    </Button>
                  )}
                </Collapse>
              </div>
            )
          })}
        </Stack>
      )}
    </Stack>
  )
}
