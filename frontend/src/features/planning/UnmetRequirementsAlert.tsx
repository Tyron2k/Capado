/**
 * Card-based display of work packages with unmet skill requirements.
 *
 * Renders pre-fetched unmet requirements grouped by work package as
 * collapsible cards. Each card shows the unmet skills with FTE gap values
 * and suggested resources that can be previewed before assignment.
 *
 * Data fetching is handled by the parent (PlanningOverviewPanel) which makes
 * a single API call for all resource types and splits the results.
 */

import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Badge,
  Box,
  Button,
  Collapse,
  Group,
  Modal,
  Stack,
  Text,
  UnstyledButton,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconAlertTriangle, IconChevronDown, IconChevronRight } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import { createAssignment, previewAssignment } from '../../api/assignments'
import { queryKeys } from '../../api/queryClient'
import { showErrorNotification } from '../../utils/errorHandling'
import { formatDate } from '../../utils/date'
import { SectionHeader } from '../../components/layout'
import type {
  AssignmentCreate,
  AssignmentPreview,
  UnmetRequirementSuggestion,
  UnmetRequirement,
} from '../../types/assignment'
import { AssignmentPreviewSummary } from './AssignmentPreviewSummary'

/** A group of unmet requirements belonging to the same work package. */
interface WpBucket {
  work_package_id: string
  work_package_name: string
  project_id: string
  project_name: string
  start_date: string
  end_date: string
  requirements: UnmetRequirement[]
}

/**
 * Groups unmet requirements by work package for card-based rendering.
 */
function buildWpBuckets(items: UnmetRequirement[]): WpBucket[] {
  const map = new Map<string, WpBucket>()
  for (const item of items) {
    let bucket = map.get(item.work_package_id)
    if (!bucket) {
      bucket = {
        work_package_id: item.work_package_id,
        work_package_name: item.work_package_name,
        project_id: item.project_id,
        project_name: item.project_name,
        start_date: item.start_date,
        end_date: item.end_date,
        requirements: [],
      }
      map.set(item.work_package_id, bucket)
    }
    bucket.requirements.push(item)
  }
  return Array.from(map.values())
}

/** Keep preview and creation on the same proposed assignment. */
function proposedAssignment(
  bucket: WpBucket,
  suggestion: UnmetRequirementSuggestion,
): AssignmentCreate {
  const common = {
    resource_id: suggestion.resource_id,
    work_package_id: bucket.work_package_id,
  }
  if (suggestion.resource_type === 'personal') {
    return {
      ...common,
      resource_type: 'personal',
      start_date: bucket.start_date,
      end_date: bucket.end_date,
      allocation_percent: 100,
    }
  }
  if (suggestion.resource_type === 'infrastructure') {
    return {
      ...common,
      resource_type: 'infrastructure',
      start_at: `${bucket.start_date}T08:00:00`,
      end_at: `${bucket.end_date}T17:00:00`,
    }
  }
  throw new Error('Unsupported resource type')
}

interface UnmetRequirementsSectionProps {
  /** Pre-fetched unmet requirement items (already filtered by resource type). */
  items: UnmetRequirement[]
  /** Section title to display. */
  title: string
  /** Whether the fetch errored. */
  error: boolean
  /** Called after a successful assignment to trigger data reload. */
  onAssigned: () => void
}

/**
 * Renders a section of unmet requirements as collapsible work package cards.
 * Data is passed in as props (fetched by parent).
 */
export function UnmetRequirementsSection({
  items,
  title,
  error,
  onAssigned,
}: UnmetRequirementsSectionProps) {
  const { t } = useTranslation()
  const buckets = useMemo(() => buildWpBuckets(items), [items])

  if (error || items.length === 0) {
    return (
      <div>
        <SectionHeader title={title} />
        <Text c="dimmed" size="sm">
          {t('planning.noUnmetRequirements')}
        </Text>
      </div>
    )
  }

  return (
    <div>
      <SectionHeader title={`${title} (${items.length})`} />
      <Stack gap="xs">
        {buckets.map((bucket) => (
          <UnmetRequirementCard
            key={bucket.work_package_id}
            bucket={bucket}
            onAssigned={onAssigned}
          />
        ))}
      </Stack>
    </div>
  )
}

/** A single card for one work package's unmet requirements. */
function UnmetRequirementCard({
  bucket,
  onAssigned,
}: {
  bucket: WpBucket
  onAssigned: () => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [activePreview, setActivePreview] = useState<{
    suggestion: UnmetRequirementSuggestion
    payload: AssignmentCreate
    result: AssignmentPreview
  } | null>(null)

  const totalGap = bucket.requirements.reduce((sum, r) => sum + r.gap, 0)

  const previewMutation = useMutation({
    mutationFn: async (suggestion: UnmetRequirementSuggestion) => {
      const payload = proposedAssignment(bucket, suggestion)
      const result = await previewAssignment(payload)
      return { suggestion, payload, result }
    },
    onSuccess: setActivePreview,
    onError: (err) => showErrorNotification(err, t('common.error'), t('common.genericError')),
  })

  const assignMutation = useMutation({
    mutationFn: (payload: AssignmentCreate) => createAssignment(payload),
    onSuccess: async () => {
      notifications.show({
        title: t('common.success'),
        message: t('planning.unmetAssigned_success'),
        color: 'green',
      })
      setActivePreview(null)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.assignments.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.gantt.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.resources.all }),
      ])
      onAssigned()
    },
    onError: (err) => showErrorNotification(err, t('common.error'), t('common.genericError')),
  })

  return (
    <Box
      style={{
        border: '1px solid light-dark(var(--mantine-color-gray-3), var(--mantine-color-dark-4))',
        borderRadius: 6,
        backgroundColor: open
          ? 'light-dark(var(--mantine-color-gray-0), var(--mantine-color-dark-6))'
          : undefined,
      }}
    >
      <Modal
        opened={activePreview !== null}
        onClose={() => {
          if (!assignMutation.isPending) setActivePreview(null)
        }}
        title={
          activePreview
            ? t('planning.unmetPreviewTitle', {
                name: activePreview.suggestion.resource_name,
              })
            : ''
        }
        size="lg"
        closeOnClickOutside={!assignMutation.isPending}
        closeOnEscape={!assignMutation.isPending}
      >
        {activePreview && (
          <Stack gap="md">
            <Text size="sm">
              {activePreview.payload.resource_type === 'personal'
                ? t('planning.unmetPreviewPersonal', {
                    start: formatDate(bucket.start_date),
                    end: formatDate(bucket.end_date),
                  })
                : t('planning.unmetPreviewInfrastructure', {
                    start: formatDate(bucket.start_date),
                    end: formatDate(bucket.end_date),
                  })}
            </Text>
            <AssignmentPreviewSummary
              preview={activePreview.result}
              disclaimer={t('planning.unmetPreviewDisclaimer')}
            />
            <Group justify="flex-end">
              <Button
                variant="default"
                onClick={() => setActivePreview(null)}
                disabled={assignMutation.isPending}
              >
                {t('common.cancel')}
              </Button>
              <Button
                onClick={() => assignMutation.mutate(activePreview.payload)}
                loading={assignMutation.isPending}
              >
                {t('planning.unmetAssign')}
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
      <UnstyledButton
        onClick={() => setOpen((s) => !s)}
        style={{ width: '100%', padding: 12 }}
        data-testid={`unmet-wp-${bucket.work_package_id}`}
      >
        <Group justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            {open ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
            <IconAlertTriangle size={16} color="var(--mantine-color-yellow-6)" />
            <Stack gap={0}>
              <Text fw={600}>{bucket.work_package_name}</Text>
              <Text size="xs" c="dimmed">
                {bucket.project_name} · {formatDate(bucket.start_date)} –{' '}
                {formatDate(bucket.end_date)}
              </Text>
            </Stack>
          </Group>
          <Badge color="yellow" variant="light">
            {t('planning.unmetGap')}: {totalGap}
          </Badge>
        </Group>
      </UnstyledButton>

      <Collapse expanded={open}>
        <Box p="md" pt={0}>
          <Stack gap="md">
            {bucket.requirements.map((req, idx) => (
              <Box key={`${req.skill_name}-${req.attribute_name}-${idx}`}>
                <Group gap="xs" mb={4}>
                  <Text size="sm" fw={500}>
                    {req.skill_name}
                    {req.attribute_name ? ` — ${req.attribute_name}` : ''}
                  </Text>
                  <Badge size="sm" color="red" variant="light">
                    {Number.isInteger(req.gap) ? req.gap : req.gap.toFixed(1)}{' '}
                    {t('planning.unmetGap').toLowerCase()}
                  </Badge>
                  <Text size="xs" c="dimmed">
                    ({t('planning.unmetNeeded')}: {req.required_quantity},{' '}
                    {t('planning.unmetAssigned')}:{' '}
                    {Number.isInteger(req.assigned_quantity)
                      ? req.assigned_quantity
                      : req.assigned_quantity.toFixed(1)}
                    )
                  </Text>
                </Group>

                {req.suggestions.length > 0 ? (
                  <Box ml="sm">
                    <Text size="xs" fw={500} c="dimmed" mb={4}>
                      {t('planning.unmetSuggestions')}
                    </Text>
                    <Stack gap={4}>
                      {req.suggestions.map((s) => (
                        <Group key={s.resource_id} gap="xs" justify="space-between">
                          <Group gap="xs">
                            <Text size="xs">{s.resource_name}</Text>
                            {s.group_name && (
                              <Text size="xs" c="dimmed">
                                ({s.group_name})
                              </Text>
                            )}
                            {s.overlapping_assignments > 0 && (
                              <Badge size="xs" variant="light" color="gray">
                                {s.overlapping_assignments} assign.
                              </Badge>
                            )}
                          </Group>
                          <Button
                            size="compact-xs"
                            variant="light"
                            loading={previewMutation.isPending && previewMutation.variables === s}
                            disabled={previewMutation.isPending || assignMutation.isPending}
                            onClick={() => {
                              setActivePreview(null)
                              previewMutation.mutate(s)
                            }}
                          >
                            {t('assignmentForm.preview')}
                          </Button>
                        </Group>
                      ))}
                    </Stack>
                  </Box>
                ) : (
                  <Text size="xs" c="dimmed" ml="sm">
                    {t('planning.unmetNoSuggestions')}
                  </Text>
                )}
              </Box>
            ))}
          </Stack>
        </Box>
      </Collapse>
    </Box>
  )
}
