/**
 * Shared editor for skill requirements, split by resource type (personal / infrastructure).
 * Used by WorkPackageForm and TemplatesPanel to avoid duplicated requirement-management UI.
 */

import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { ActionIcon, Group, NumberInput, Select, Stack, Table, Text } from '@mantine/core'
import { IconPlus, IconTrash } from '@tabler/icons-react'
import { getSkillsWithAttributes } from '../api/skills'
import type { SkillWithAttributes } from '../types/skill'
import { useTranslation } from '../i18n'
import { queryKeys } from '../api/queryClient'

/** Minimal requirement shape shared by WorkPackageRequirement and TemplateRequirement. */
interface Requirement {
  id: string
  skill_id: string
  skill_name: string
  skill_attribute_id: string | null
  skill_attribute_name: string | null
  quantity: number
}

interface RequirementsEditorProps {
  /** Current list of requirements. */
  requirements: Requirement[]
  /** Called when user adds a requirement (skill_id, skill_attribute_id, quantity). */
  onAdd: (data: {
    skill_id: string
    skill_attribute_id: string | null
    quantity: number
  }) => Promise<void>
  /** Called when user removes a requirement by id. */
  onRemove: (req: Requirement) => Promise<void>
  /** Whether the add/remove actions are loading. */
  loading?: boolean
}

interface SectionProps {
  resourceType: 'personal' | 'infrastructure'
  title: string
  requirements: Requirement[]
  skills: SkillWithAttributes[]
  onAdd: RequirementsEditorProps['onAdd']
  onRemove: RequirementsEditorProps['onRemove']
  loading?: boolean
}

/**
 * A single resource-type section (table + add form) within the requirements editor.
 */
function RequirementSection({
  resourceType,
  title,
  requirements,
  skills,
  onAdd,
  onRemove,
  loading,
}: SectionProps) {
  const { t } = useTranslation()
  const [skillId, setSkillId] = useState<string | null>(null)
  const [attrId, setAttrId] = useState<string | null>(null)
  const [quantity, setQuantity] = useState<number | string>(1)
  const [adding, setAdding] = useState(false)

  // Filter skills for this resource type
  const filteredSkills = skills.filter((s) => s.resource_type === resourceType)
  const skillOptions = filteredSkills.map((s) => ({ value: s.id, label: s.name }))
  const selectedSkill = filteredSkills.find((s) => s.id === skillId)
  const attributeOptions = selectedSkill
    ? selectedSkill.attributes.map((a) => ({ value: a.id, label: a.name }))
    : []

  // Filter requirements to only show those belonging to skills of this type
  const skillIds = new Set(filteredSkills.map((s) => s.id))
  const filteredRequirements = requirements.filter((r) => skillIds.has(r.skill_id))

  const handleAdd = async () => {
    if (!skillId || !quantity || Number(quantity) < 1) return
    setAdding(true)
    try {
      await onAdd({
        skill_id: skillId,
        skill_attribute_id: attrId || null,
        quantity: Number(quantity),
      })
      setSkillId(null)
      setAttrId(null)
      setQuantity(1)
    } finally {
      setAdding(false)
    }
  }

  return (
    <Stack gap="xs">
      <Text fw={500} size="sm">
        {title}
      </Text>

      {filteredRequirements.length > 0 && (
        <Table striped withTableBorder fz="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('requirements.skill')}</Table.Th>
              <Table.Th>{t('requirements.attribute')}</Table.Th>
              <Table.Th>{t('requirements.quantity')}</Table.Th>
              <Table.Th style={{ width: 40 }} aria-label={t('common.actions')} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {filteredRequirements.map((req) => (
              <Table.Tr key={req.id}>
                <Table.Td>{req.skill_name}</Table.Td>
                <Table.Td>{req.skill_attribute_name || '—'}</Table.Td>
                <Table.Td>{req.quantity}</Table.Td>
                <Table.Td>
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    size="xs"
                    onClick={() => onRemove(req)}
                    disabled={loading}
                    aria-label={t('common.delete')}
                  >
                    <IconTrash size={12} />
                  </ActionIcon>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Group align="flex-end" gap="xs">
        <Select
          placeholder={t('requirements.skill')}
          data={skillOptions}
          value={skillId}
          onChange={(val) => {
            setSkillId(val)
            setAttrId(null)
          }}
          searchable
          clearable
          size="xs"
          style={{ flex: 1 }}
        />
        <Select
          placeholder={t('requirements.attribute')}
          data={attributeOptions}
          value={attrId}
          onChange={setAttrId}
          searchable
          clearable
          disabled={!skillId}
          size="xs"
          style={{ flex: 1 }}
        />
        <NumberInput
          value={quantity}
          onChange={setQuantity}
          min={1}
          size="xs"
          style={{ width: 60 }}
        />
        <ActionIcon
          color="teal"
          onClick={handleAdd}
          loading={adding}
          disabled={!skillId}
          size="sm"
          aria-label={t('requirements.addAriaLabel')}
        >
          <IconPlus size={14} />
        </ActionIcon>
      </Group>
    </Stack>
  )
}

/**
 * Requirements editor split into personal and infrastructure sections.
 * Caches skills at the module level to avoid re-fetching on every mount
 * (skills rarely change during a session).
 */

export function RequirementsEditor({
  requirements,
  onAdd,
  onRemove,
  loading,
}: RequirementsEditorProps) {
  const { t } = useTranslation()
  /**
   * THIS REPLACES A HAND-ROLLED MODULE-LEVEL CACHE, and it is the clearest case in the whole migration.
   *
   * What was here: a module variable holding the skill list, a second variable holding the in-flight
   * promise so concurrent callers would share one request, and a comment describing it as cached "for
   * the session lifetime". That is a cache with request deduplication — written by hand, and correct as
   * far as it went.
   *
   * What it could not do is GO STALE. Nothing ever cleared those variables, so adding a skill in the
   * skills panel left every requirements editor in the app offering the old catalogue until the page was
   * reloaded. The editor is where a requirement is created, which means the skill somebody had just added
   * in order to require it was the one thing they could not pick.
   *
   * `skills.withAttributes('all')` gives the same deduplication and the same session-long reuse, plus the
   * invalidation the module variables had no way to express — the skills panel already invalidates
   * `skills.all`, written before anything read it.
   *
   * The unparameterised call is a DIFFERENT key from `withAttributes('personal')`: this editor offers
   * every skill regardless of resource type, and the panel's tab offers one type's.
   */
  const skillsQuery = useQuery({
    queryKey: queryKeys.skills.withAttributes('all'),
    queryFn: () => getSkillsWithAttributes(),
  })
  const skills: SkillWithAttributes[] = skillsQuery.data ?? []

  return (
    <Stack gap="md">
      <RequirementSection
        resourceType="personal"
        title={t('requirements.personalTitle')}
        requirements={requirements}
        skills={skills}
        onAdd={onAdd}
        onRemove={onRemove}
        loading={loading}
      />
      <RequirementSection
        resourceType="infrastructure"
        title={t('requirements.infrastructureTitle')}
        requirements={requirements}
        skills={skills}
        onAdd={onAdd}
        onRemove={onRemove}
        loading={loading}
      />
    </Stack>
  )
}
