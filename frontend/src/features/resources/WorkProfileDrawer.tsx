/**
 * Drawer for assigning a week profile to one resource, dated.
 *
 * Without this, week profiles could be created but never assigned, so every capacity
 * calculation fell back to the default profile — part-time was unmodellable through the
 * UI even though the backend has supported it since ADR-004.
 *
 * The drawer states the resolution order, because it is the part that surprises people:
 * an individual binding wins over the resource's group, which wins over that group's
 * parent, which loses to the default profile only if nothing else matches. Someone
 * removing an individual binding needs to know what will take over.
 *
 * Bindings are DATED rather than replaced. A contract change on 1 July is a new binding
 * from that date, not an edit of the old one — otherwise last quarter's capacity would
 * silently change to match this quarter's contract, and a baseline taken back then would
 * no longer reconcile.
 */

import { useEffect, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Drawer,
  Group,
  Select,
  Stack,
  Table,
  Text,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconInfoCircle, IconPlus, IconTrash } from '@tabler/icons-react'
import { DataTable } from '../../components/layout'
import { DateField } from '../../components/DateField'
import { showErrorNotification } from '../../utils/errorHandling'
import {
  createBinding,
  deleteBinding,
  formatMinutes,
  listBindings,
  listWorkWeekProfiles,
  type ResourceWorkProfileBinding,
  type WorkWeekProfile,
} from '../../api/calendar'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { formatDate, toIsoDate, type DateFormValue } from '../../utils/date'

interface WorkProfileDrawerProps {
  resourceId: string
  resourceName: string
  /** The resource's group, so a group-level binding can be shown as the fallback. */
  groupId?: string | null
  opened: boolean
  onClose: () => void
}

export function WorkProfileDrawer({
  resourceId,
  resourceName,
  groupId,
  opened,
  onClose,
}: WorkProfileDrawerProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [profileId, setProfileId] = useState<string | null>(null)
  const [validFrom, setValidFrom] = useState<DateFormValue>(null)

  /**
   * Three reads, three queries — where the hand-written version had one load function.
   *
   * Splitting them is not tidiness. The profile LIST is organisation-wide and shared with
   * WeekProfilesTab, so it comes from cache here; the two binding lists belong to this resource and
   * this group. Bundled into one `Promise.all` they shared one loading flag and one cache lifetime, so
   * opening the drawer refetched the profile list every time even though nothing about it had changed.
   */
  const profilesQuery = useQuery({
    queryKey: queryKeys.capacity.weekProfiles(),
    queryFn: () => listWorkWeekProfiles(),
    enabled: opened,
  })
  const ownQuery = useQuery({
    queryKey: queryKeys.capacity.profileBindings(resourceId),
    queryFn: () => listBindings({ resource_id: resourceId }),
    enabled: opened && Boolean(resourceId),
  })
  /**
   * Loaded separately so the drawer can NAME what takes over when an individual binding is removed,
   * rather than leaving the user to guess. Keyed by the group, so two resources in the same group
   * share the answer.
   */
  const groupQuery = useQuery({
    queryKey: queryKeys.capacity.profileBindings(groupId ?? 'no-group'),
    queryFn: () => listBindings({ group_id: groupId as string }),
    enabled: opened && Boolean(groupId),
  })

  const profiles: WorkWeekProfile[] = profilesQuery.data ?? []
  const own: ResourceWorkProfileBinding[] = ownQuery.data ?? []
  const groupBindings: ResourceWorkProfileBinding[] = groupQuery.data ?? []
  const loading = opened && (profilesQuery.isPending || ownQuery.isPending)

  useEffect(() => {
    const error = profilesQuery.error ?? ownQuery.error ?? groupQuery.error
    if (error) {
      showErrorNotification(error, t('common.error'), t('workProfiles.loadFailed'))
    }
  }, [profilesQuery.error, ownQuery.error, groupQuery.error, t])

  /**
   * A PROFILE BINDING IS CAPACITY: it decides which week profile's minutes this resource actually has.
   * Same four keys as the other capacity screens.
   */
  const invalidateAfterCapacityChange = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.capacity.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
    ])
  }

  const profileName = (id: string) => profiles.find((p) => p.id === id)?.name ?? id.slice(0, 8)

  const weeklyMinutes = (id: string) => {
    const profile = profiles.find((p) => p.id === id)
    if (!profile) return null
    return (
      profile.monday_minutes +
      profile.tuesday_minutes +
      profile.wednesday_minutes +
      profile.thursday_minutes +
      profile.friday_minutes +
      profile.saturday_minutes +
      profile.sunday_minutes
    )
  }

  const addMutation = useMutation({
    mutationFn: (payload: Parameters<typeof createBinding>[0]) => createBinding(payload),
    onSuccess: async () => {
      notifications.show({
        title: t('common.success'),
        message: t('workProfiles.created'),
        color: 'green',
      })
      setProfileId(null)
      setValidFrom(null)
      await invalidateAfterCapacityChange()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const saving = addMutation.isPending

  const handleAdd = () => {
    if (!profileId || !validFrom) return
    addMutation.mutate({
      profile_id: profileId,
      resource_id: resourceId,
      valid_from: toIsoDate(validFrom),
    })
  }

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteBinding(id),
    onSuccess: invalidateAfterCapacityChange,
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const handleDelete = (id: string) => {
    deleteMutation.mutate(id)
  }

  const sorted = [...own].sort((a, b) => b.valid_from.localeCompare(a.valid_from))

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      title={t('workProfiles.title', { name: resourceName })}
      position="right"
      size="lg"
    >
      <Stack gap="md">
        {/* The resolution order, stated where the decision is made. */}
        <Alert icon={<IconInfoCircle size={16} />} color="blue">
          <Stack gap={4}>
            <Text size="sm">{t('workProfiles.resolutionOrder')}</Text>
            {own.length === 0 && (
              <Text size="sm">
                {groupBindings.length > 0
                  ? t('workProfiles.fallbackGroup', {
                      profile: profileName(groupBindings[0].profile_id),
                    })
                  : t('workProfiles.fallbackDefault')}
              </Text>
            )}
          </Stack>
        </Alert>

        <DataTable
          loading={loading}
          empty={sorted.length === 0}
          emptyMessage={t('workProfiles.none')}
          head={
            <Table.Tr>
              <Table.Th>{t('workProfiles.profile')}</Table.Th>
              <Table.Th>{t('workProfiles.validFrom')}</Table.Th>
              <Table.Th>{t('workProfiles.weekly')}</Table.Th>
              <Table.Th />
            </Table.Tr>
          }
        >
          {sorted.map((binding, index) => {
            const minutes = weeklyMinutes(binding.profile_id)
            return (
              <Table.Tr key={binding.id}>
                <Table.Td>
                  <Group gap="xs">
                    <Text size="sm">{profileName(binding.profile_id)}</Text>
                    {/* Newest start date wins today; older rows are history, not
                        competitors, and labelling them avoids the impression that two
                        profiles apply at once. */}
                    {index === 0 && (
                      <Badge color="blue" variant="light">
                        {t('workProfiles.active')}
                      </Badge>
                    )}
                  </Group>
                </Table.Td>
                <Table.Td>{formatDate(binding.valid_from)}</Table.Td>
                <Table.Td>{minutes === null ? '—' : `${formatMinutes(minutes)} h`}</Table.Td>
                <Table.Td ta="right">
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    size="sm"
                    aria-label={t('common.delete')}
                    onClick={() => handleDelete(binding.id)}
                  >
                    <IconTrash size={14} />
                  </ActionIcon>
                </Table.Td>
              </Table.Tr>
            )
          })}
        </DataTable>

        <Group align="flex-end" gap="sm">
          <Select
            label={t('workProfiles.profile')}
            placeholder={t('workProfiles.selectProfile')}
            data={profiles.map((p) => ({ value: p.id, label: p.name }))}
            value={profileId}
            onChange={setProfileId}
            style={{ flex: 1 }}
          />
          <DateField
            label={t('workProfiles.validFrom')}
            description={t('workProfiles.validFromDesc')}
            value={validFrom}
            onChange={setValidFrom}
          />
          <Button
            leftSection={<IconPlus size={14} />}
            loading={saving}
            disabled={!profileId || !validFrom}
            onClick={handleAdd}
          >
            {t('common.add')}
          </Button>
        </Group>

        <Text size="xs" c="dimmed">
          {t('workProfiles.datedHint')}
        </Text>
      </Stack>
    </Drawer>
  )
}
