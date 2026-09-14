/**
 * Card-based display of work packages with unmet skill requirements.
 *
 * Renders pre-fetched unmet requirements grouped by work package as
 * collapsible cards. Each card shows the unmet skills with FTE gap values
 * and suggested resources that can be directly assigned via an "Assign" button.
 *
 * Data fetching is handled by the parent (PlanningOverviewPanel) which makes
 * a single API call for all resource types and splits the results.
 */

import { useMemo, useState } from 'react'
import { Badge, Box, Button, Collapse, Group, Stack, Text, UnstyledButton } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconAlertTriangle, IconChevronDown, IconChevronRight } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import { createAssignment } from '../../api/assignments'
import { showErrorNotification } from '../../utils/errorHandling'
import { formatDate } from '../../utils/date'
import { SectionHeader } from '../../components/layout'
import type { UnmetRequirementSuggestion, UnmetRequirement } from '../../types/assignment'

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
  const [open, setOpen] = useState(false)
  const [assigningId, setAssigningId] = useState<string | null>(null)

  const totalGap = bucket.requirements.reduce((sum, r) => sum + r.gap, 0)

  const handleAssign = async (suggestion: UnmetRequirementSuggestion) => {
    setAssigningId(suggestion.resource_id)
    try {
      const isInfra = suggestion.resource_type === 'infrastructure'
      await createAssignment({
        resource_id: suggestion.resource_id,
        work_package_id: bucket.work_package_id,
        resource_type: suggestion.resource_type as 'personal' | 'infrastructure',
        ...(isInfra
          ? {
              start_at: `${bucket.start_date}T08:00:00`,
              end_at: `${bucket.end_date}T17:00:00`,
            }
          : {
              start_date: bucket.start_date,
              end_date: bucket.end_date,
              allocation_percent: 100,
            }),
      })
      notifications.show({
        title: t('common.success'),
        message: t('planning.unmetAssigned_success'),
        color: 'green',
      })
      onAssigned()
    } catch (err: unknown) {
      showErrorNotification(err, t('common.error'), t('common.genericError'))
    } finally {
      setAssigningId(null)
    }
  }

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
                            loading={assigningId === s.resource_id}
                            onClick={() => handleAssign(s)}
                          >
                            {t('planning.unmetAssign')}
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
