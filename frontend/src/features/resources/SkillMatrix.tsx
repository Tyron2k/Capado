/**
 * Skill assignment component for a resource (personal or infrastructure).
 * Shows skills grouped by skill name with checkboxes for each attribute.
 * Allows assigning/removing skill attributes via checkbox toggle.
 */

import { useEffect } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Badge, Checkbox, Group, Select, Skeleton, Stack, Table, Text } from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { showErrorNotification } from '../../utils/errorHandling'
import { IconInfoCircle } from '@tabler/icons-react'
import type { SkillWithAttributes, ResourceSkillAssignment } from '../../types/skill'
import {
  addInfrastructureResourceSkill,
  addPersonalResourceSkill,
  getInfrastructureResourceSkills,
  getPersonalResourceSkills,
  getSkillsWithAttributes,
  removeInfrastructureResourceSkill,
  removePersonalResourceSkill,
  updateInfrastructureResourceSkill,
  updatePersonalResourceSkill,
} from '../../api/skills'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'

interface QualificationMatrixProps {
  resourceId: string
  /** Resource type determines which API endpoints to use. */
  resourceType?: 'personal' | 'infrastructure'
}

export function SkillMatrix({ resourceId, resourceType = 'personal' }: QualificationMatrixProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const getSkills =
    resourceType === 'personal' ? getPersonalResourceSkills : getInfrastructureResourceSkills
  const addSkill =
    resourceType === 'personal' ? addPersonalResourceSkill : addInfrastructureResourceSkill
  const removeSkill =
    resourceType === 'personal' ? removePersonalResourceSkill : removeInfrastructureResourceSkill
  const updateSkill =
    resourceType === 'personal' ? updatePersonalResourceSkill : updateInfrastructureResourceSkill

  const skillsQuery = useQuery({
    queryKey: queryKeys.skills.withAttributes(resourceType),
    queryFn: () => getSkillsWithAttributes(resourceType),
  })
  const qualificationsQuery = useQuery({
    queryKey: queryKeys.resources.qualifications(resourceId),
    queryFn: () => getSkills(resourceId),
  })

  const skills: SkillWithAttributes[] = skillsQuery.data ?? []
  const assignments: ResourceSkillAssignment[] = qualificationsQuery.data ?? []
  const loading = skillsQuery.isPending || qualificationsQuery.isPending

  useEffect(() => {
    const error = skillsQuery.error ?? qualificationsQuery.error
    if (error) showErrorNotification(error, t('common.error'), t('skillMatrix.loadFailed'))
  }, [skillsQuery.error, qualificationsQuery.error, t])

  const qualificationsKey = queryKeys.resources.qualifications(resourceId)

  /**
   * THIS SCREEN STAYS OPTIMISTIC.
   *
   * Toggling a qualification has to feel instant — a foreman ticks a row of boxes, and a spinner per
   * box would make that unusable. So the change is written into the cache before the request and rolled
   * back if it fails.
   *
   * TWO THINGS ARE BETTER THAN THE HAND-WRITTEN VERSION, and one thing is honestly not the disaster it
   * looks like. The snapshot now comes from the CACHE inside `onMutate` rather than from React state at
   * click time, and `cancelQueries` first stops an in-flight refetch from landing on top of the
   * optimistic write. The old click-time snapshot was genuinely wrong under concurrent toggles — a
   * second click's snapshot already contained the first's unconfirmed row — but `onSettled` invalidates
   * either way, so the server's answer replaced the bad rollback almost immediately. The observable
   * consequence was a flicker, not a lost qualification. Measured, not assumed: reinstating the old
   * snapshot does not fail the concurrency test below, because the refetch heals it before the
   * assertion can see it.
   *
   * So the reason to prefer this shape is that the rollback is a STOPGAP with a correct successor,
   * rather than the last word — not that it fixes a data-loss bug. The five-key set is the skill set
   * from SkillsPanel: a qualification is what a requirement is measured against.
   */
  const invalidateAfterQualificationChange = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
    ])

  async function snapshotForRollback() {
    await queryClient.cancelQueries({ queryKey: qualificationsKey })
    return queryClient.getQueryData<ResourceSkillAssignment[]>(qualificationsKey) ?? []
  }

  /**
   * Persist a change to a held qualification's bounds.
   *
   * Sends only the changed field, so an explicit null clears it rather than being read as
   * "leave alone" — that is what makes a renewed certificate expressible.
   */
  const boundsMutation = useMutation({
    mutationFn: ({
      assignment,
      change,
    }: {
      assignment: ResourceSkillAssignment
      change: { valid_until?: string | null; level?: number | null }
    }) => updateSkill(resourceId, assignment.id, change),
    onMutate: async ({ assignment, change }) => {
      const previous = await snapshotForRollback()
      queryClient.setQueryData<ResourceSkillAssignment[]>(qualificationsKey, (current) =>
        (current ?? []).map((a) => (a.id === assignment.id ? { ...a, ...change } : a)),
      )
      return { previous }
    },
    onError: (error, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(qualificationsKey, context.previous)
      showErrorNotification(error, t('common.error'), t('skillMatrix.saveFailed'))
    },
    onSettled: () => invalidateAfterQualificationChange(),
  })

  const handleBoundsChange = (
    assignment: ResourceSkillAssignment,
    change: { valid_until?: string | null; level?: number | null },
  ) => {
    boundsMutation.mutate({ assignment, change })
  }

  const toggleMutation = useMutation({
    mutationFn: ({
      skillAttributeId,
      existing,
    }: {
      skillAttributeId: string
      existing: ResourceSkillAssignment | undefined
    }) =>
      existing
        ? removeSkill(resourceId, existing.id).then(() => undefined)
        : addSkill(resourceId, { skill_attribute_id: skillAttributeId }).then(() => undefined),
    onMutate: async ({ skillAttributeId, existing }) => {
      const previous = await snapshotForRollback()
      if (existing) {
        queryClient.setQueryData<ResourceSkillAssignment[]>(qualificationsKey, (current) =>
          (current ?? []).filter((a) => a.id !== existing.id),
        )
      } else {
        let skillName = ''
        let attributeName = ''
        for (const skill of skills) {
          const attr = skill.attributes.find((a) => a.id === skillAttributeId)
          if (attr) {
            skillName = skill.name
            attributeName = attr.name
            break
          }
        }
        const tempAssignment: ResourceSkillAssignment = {
          id: `temp-${skillAttributeId}`,
          skill_attribute_id: skillAttributeId,
          skill_id: '',
          skill_name: skillName,
          attribute_name: attributeName,
          // The matrix toggles a qualification on and off; it does not carry bounds.
          // Expiry and level are entered on the resource's skill drawer, so the
          // optimistic row here states "no bounds recorded" rather than guessing.
          valid_from: null,
          valid_until: null,
          level: null,
        }
        queryClient.setQueryData<ResourceSkillAssignment[]>(qualificationsKey, (current) => [
          ...(current ?? []),
          tempAssignment,
        ])
      }
      return { previous }
    },
    onError: (error, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(qualificationsKey, context.previous)
      showErrorNotification(error, t('common.error'), t('skillMatrix.saveFailed'))
    },
    onSettled: () => invalidateAfterQualificationChange(),
  })

  function handleToggle(skillAttributeId: string) {
    toggleMutation.mutate({
      skillAttributeId,
      existing: assignments.find((a) => a.skill_attribute_id === skillAttributeId),
    })
  }

  /**
   * Which cells show a spinner. Read off the mutations' own variables rather than kept in a Set that
   * has to be added to and removed from in a `finally` — a path that leaks a stuck spinner whenever an
   * early return skips it.
   */
  const loadingCells = new Set<string>(
    [
      toggleMutation.isPending ? toggleMutation.variables.skillAttributeId : null,
      boundsMutation.isPending ? boundsMutation.variables.assignment.skill_attribute_id : null,
    ].filter((v): v is string => v !== null),
  )

  if (loading) {
    return (
      <div>
        <Skeleton height={20} width="60%" mb="sm" />
        <Skeleton height={200} />
      </div>
    )
  }

  if (skills.length === 0) {
    return (
      <Alert icon={<IconInfoCircle size={16} />} title={t('skillMatrix.noData')} color="blue">
        {t('skillMatrix.noSkills')}
      </Alert>
    )
  }

  const skillsWithAttrs = skills.filter((s) => s.attributes.length > 0)

  if (skillsWithAttrs.length === 0) {
    return (
      <Alert icon={<IconInfoCircle size={16} />} title={t('skillMatrix.noData')} color="blue">
        {t('skillMatrix.noAttributes')}
      </Alert>
    )
  }

  return (
    <Stack gap="md">
      {skillsWithAttrs.map((skill) => (
        <div key={skill.id}>
          <Text fw={600} size="sm" mb="xs">
            {skill.name}
          </Text>
          <Table striped highlightOnHover withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('skillMatrix.attribute')}</Table.Th>
                <Table.Th style={{ width: 80, textAlign: 'center' }}>
                  {t('skillMatrix.assigned')}
                </Table.Th>
                <Table.Th style={{ width: 190 }}>{t('skillMatrix.validUntil')}</Table.Th>
                <Table.Th style={{ width: 130 }}>{t('skillMatrix.level')}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {skill.attributes.map((attr) => {
                const assignment = assignments.find((a) => a.skill_attribute_id === attr.id)
                const isChecked = !!assignment
                const isCellLoading = loadingCells.has(attr.id)
                const isTemp = assignment?.id.startsWith('temp-') ?? false
                const expiry = assignment?.valid_until ? new Date(assignment.valid_until) : null

                // Compared against today deliberately: this badge answers "does this need
                // attention now", which is a different question from whether the
                // qualification covers a given piece of work. The planning check runs
                // against the assignment's own dates on the backend.
                const daysLeft = expiry
                  ? Math.ceil((expiry.getTime() - Date.now()) / 86_400_000)
                  : null

                return (
                  <Table.Tr key={attr.id}>
                    <Table.Td>{attr.name}</Table.Td>
                    <Table.Td style={{ textAlign: 'center' }}>
                      <Checkbox
                        checked={isChecked}
                        disabled={isCellLoading}
                        data-testid={`qualification-${attr.id}`}
                        onChange={() => handleToggle(attr.id)}
                        aria-label={`${skill.name} – ${attr.name}`}
                      />
                    </Table.Td>
                    <Table.Td>
                      {assignment && !isTemp ? (
                        <Group gap="xs" wrap="nowrap">
                          <DateInput
                            // Mantine hands back a plain 'YYYY-MM-DD' string, which is
                            // exactly what the API stores. Going via Date and
                            // toISOString() would convert to UTC first and shift the day
                            // backwards east of Greenwich — 1 March saved as 28 February.
                            value={assignment.valid_until ?? null}
                            onChange={(value) =>
                              void handleBoundsChange(assignment, {
                                valid_until: value || null,
                              })
                            }
                            disabled={isCellLoading}
                            clearable
                            size="xs"
                            valueFormat="DD.MM.YYYY"
                            placeholder={t('skillMatrix.noExpiry')}
                            aria-label={`${attr.name} – ${t('skillMatrix.validUntil')}`}
                            style={{ minWidth: 110 }}
                          />
                          {daysLeft !== null && daysLeft < 0 && (
                            <Badge color="red" size="sm" variant="light">
                              {t('skillMatrix.expired')}
                            </Badge>
                          )}
                          {daysLeft !== null && daysLeft >= 0 && daysLeft <= 90 && (
                            <Badge color="orange" size="sm" variant="light">
                              {t('skillMatrix.expiringSoon', { days: daysLeft })}
                            </Badge>
                          )}
                        </Group>
                      ) : (
                        <Text size="xs" c="dimmed">
                          –
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      {assignment && !isTemp ? (
                        <Select
                          value={assignment.level !== null ? String(assignment.level) : null}
                          onChange={(value) =>
                            void handleBoundsChange(assignment, {
                              level: value ? Number(value) : null,
                            })
                          }
                          data={['1', '2', '3', '4', '5']}
                          disabled={isCellLoading}
                          clearable
                          size="xs"
                          placeholder={t('skillMatrix.noLevel')}
                          aria-label={`${attr.name} – ${t('skillMatrix.level')}`}
                        />
                      ) : (
                        <Text size="xs" c="dimmed">
                          –
                        </Text>
                      )}
                    </Table.Td>
                  </Table.Tr>
                )
              })}
            </Table.Tbody>
          </Table>
        </div>
      ))}
    </Stack>
  )
}
