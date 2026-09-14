/**
 * Drawer for managing absences of a resource.
 *
 * The reason is only planned vs unplanned. Naming the cause would make this a health
 * datum for no gain: the capacity calculation uses the date range and the share, never
 * the reason (migration 013).
 * Shows a list of existing absences and a form to create new ones.
 */

import { useEffect, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ActionIcon,
  Badge,
  Button,
  Drawer,
  Group,
  Loader,
  NumberInput,
  Select,
  Stack,
  Table,
  Text,
  Textarea,
} from '@mantine/core'
import { DataTable } from '../../components/layout'
import { DateField } from '../../components/DateField'
import { notifications } from '@mantine/notifications'
import { showErrorNotification } from '../../utils/errorHandling'
import { IconPlus, IconTrash } from '@tabler/icons-react'
import {
  createAbsence,
  deleteAbsence,
  getAbsences,
  type Absence,
  type AbsenceReason,
  type AbsenceStatus,
} from '../../api/absences'
import type { ResourceType } from '../../types/assignment'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { formatDate } from '../../utils/date'

interface AbsenceDrawerProps {
  resourceId: string
  resourceName: string
  resourceType: ResourceType
  opened: boolean
  onClose: () => void
}

// Both resource types offer the same two reasons. Machine maintenance and a booked
// training course are both simply foreseeable, so a separate infrastructure list
// would carry no extra information.
const ALL_REASONS: { value: AbsenceReason; labelKey: string; color: string }[] = [
  { value: 'planned', labelKey: 'absences.planned', color: 'blue' },
  { value: 'unplanned', labelKey: 'absences.unplanned', color: 'orange' },
]

const PERSONAL_REASONS = ALL_REASONS
const INFRA_REASONS = ALL_REASONS

export function AbsenceDrawer({
  resourceId,
  resourceName,
  resourceType,
  opened,
  onClose,
}: AbsenceDrawerProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  // Form state
  const [reason, setReason] = useState<AbsenceReason | null>(null)
  // Defaults to confirmed: an absence somebody types in is a fact unless they say
  // otherwise. Both statuses reduce capacity identically.
  const [status, setStatus] = useState<AbsenceStatus>('confirmed')
  const [startDate, setStartDate] = useState<string | null>(null)
  const [endDate, setEndDate] = useState<string | null>(null)
  const [percent, setPercent] = useState<number>(100)
  const [note, setNote] = useState('')

  /**
   * `enabled: opened` keeps the drawer's request tied to the drawer being open.
   *
   * The hand-written version had the same behaviour as an early return inside the effect. As a query
   * option it also means the ANSWER survives closing and reopening: a planner who closes the drawer to
   * check a date and comes back gets the list from cache instead of a spinner.
   */
  const absencesQuery = useQuery({
    queryKey: queryKeys.capacity.absences(resourceId),
    queryFn: () => getAbsences(resourceId),
    enabled: opened && Boolean(resourceId),
  })
  const absences: Absence[] = absencesQuery.data ?? []
  const loading = absencesQuery.isPending && opened

  useEffect(() => {
    if (absencesQuery.error) {
      showErrorNotification(absencesQuery.error, t('common.error'), t('absences.loadFailed'))
    }
  }, [absencesQuery.error, t])

  /**
   * AN ABSENCE IS CAPACITY, exactly as a week profile and a holiday are.
   *
   * Entering one reduces the minutes this resource has, so an assignment that fitted may stop fitting
   * — and the conflict and the dashboard finding are computed from that, not from this drawer. Same
   * four keys as WeekProfilesTab and HolidaysTab: this is now the shape for anything touching
   * available minutes.
   */
  const invalidateAfterCapacityChange = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.capacity.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
    ])
  }

  const createMutation = useMutation({
    mutationFn: (payload: Parameters<typeof createAbsence>[0]) => createAbsence(payload),
    onSuccess: async () => {
      notifications.show({
        title: t('common.created'),
        message: t('absences.created'),
        color: 'green',
      })
      setReason(null)
      setStartDate(null)
      setEndDate(null)
      setPercent(100)
      setNote('')
      await invalidateAfterCapacityChange()
    },
    onError: (error) => showErrorNotification(error, t('common.error'), t('common.genericError')),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteAbsence(id),
    onSuccess: async () => {
      notifications.show({
        title: t('common.deleted'),
        message: t('absences.deleted'),
        color: 'green',
      })
      await invalidateAfterCapacityChange()
    },
    onError: (error) => showErrorNotification(error, t('common.error'), t('common.genericError')),
  })

  const saving = createMutation.isPending

  const handleCreate = () => {
    if (!reason || !startDate || !endDate) return
    createMutation.mutate({
      resource_id: resourceId,
      resource_type: resourceType,
      reason,
      start_date: startDate,
      end_date: endDate,
      allocation_percent: percent,
      status,
      note: note.trim() || null,
    })
  }

  const handleDelete = (id: string) => {
    deleteMutation.mutate(id)
  }

  const reasonOptions = resourceType === 'personal' ? PERSONAL_REASONS : INFRA_REASONS

  const reasonLabel = (r: AbsenceReason) => {
    const opt = ALL_REASONS.find((o) => o.value === r)
    return opt ? t(opt.labelKey) : r
  }

  const reasonColor = (r: AbsenceReason) => {
    const opt = ALL_REASONS.find((o) => o.value === r)
    return opt?.color ?? 'gray'
  }

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      title={`${t('absences.title')} — ${resourceName}`}
      position="right"
      size="lg"
      trapFocus
      returnFocus
    >
      <Stack gap="md">
        {/* Create form */}
        <Stack gap="xs">
          <Text fw={600} size="sm">
            {t('absences.addNew')}
          </Text>
          <Select
            label={t('absences.reason')}
            placeholder={t('absences.selectReason')}
            data={reasonOptions.map((o) => ({ value: o.value, label: t(o.labelKey) }))}
            value={reason}
            onChange={(val) => setReason(val as AbsenceReason)}
            required
          />
          <Group grow>
            <DateField
              label={t('absences.startDate')}
              placeholder={t('absences.selectDate')}
              value={startDate}
              onChange={setStartDate}
              required
            />
            <DateField
              label={t('absences.endDate')}
              placeholder={t('absences.selectDate')}
              value={endDate}
              onChange={setEndDate}
              required
            />
          </Group>
          <Select
            label={t('absences.status')}
            description={t('absences.statusDesc')}
            data={[
              { value: 'confirmed', label: t('absences.statusValue.confirmed') },
              { value: 'provisional', label: t('absences.statusValue.provisional') },
            ]}
            value={status}
            onChange={(value) => setStatus((value as AbsenceStatus) || 'confirmed')}
            allowDeselect={false}
          />
          <NumberInput
            label={t('absences.allocationPercent')}
            value={percent}
            onChange={(val) => setPercent(typeof val === 'number' ? val : 100)}
            min={5}
            max={100}
            step={5}
            suffix="%"
          />
          <Textarea
            label={t('absences.note')}
            placeholder={t('absences.notePlaceholder')}
            value={note}
            onChange={(e) => setNote(e.currentTarget.value)}
            rows={2}
          />
          <Group justify="flex-end">
            <Button
              leftSection={<IconPlus size={14} />}
              onClick={handleCreate}
              loading={saving}
              disabled={!reason || !startDate || !endDate}
              size="xs"
            >
              {t('absences.add')}
            </Button>
          </Group>
        </Stack>

        {/* List */}
        {loading ? (
          <Loader size="sm" />
        ) : (
          <DataTable
            empty={absences.length === 0}
            emptyMessage={t('absences.empty')}
            head={
              <Table.Tr>
                <Table.Th>{t('absences.reason')}</Table.Th>
                <Table.Th>{t('absences.period')}</Table.Th>
                <Table.Th>{t('absences.allocationPercent')}</Table.Th>
                <Table.Th aria-label={t('common.actions')} />
              </Table.Tr>
            }
          >
            {absences.map((ab) => (
              <Table.Tr key={ab.id}>
                <Table.Td>
                  <Group gap={4} wrap="nowrap">
                    <Badge size="sm" color={reasonColor(ab.reason)} variant="light">
                      {reasonLabel(ab.reason)}
                    </Badge>
                    {/* Only the provisional case is marked. Badging every confirmed
                        absence too would double the visual noise to say "normal". */}
                    {ab.status === 'provisional' && (
                      <Badge size="sm" color="yellow" variant="outline">
                        {t('absences.statusValue.provisional')}
                      </Badge>
                    )}
                  </Group>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">
                    {formatDate(ab.start_date)} – {formatDate(ab.end_date)}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{ab.allocation_percent}%</Text>
                </Table.Td>
                <Table.Td>
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    size="sm"
                    data-testid={`absence-delete-${ab.id}`}
                    onClick={() => handleDelete(ab.id)}
                    aria-label={t('common.delete')}
                  >
                    <IconTrash size={14} />
                  </ActionIcon>
                </Table.Td>
              </Table.Tr>
            ))}
          </DataTable>
        )}
      </Stack>
    </Drawer>
  )
}
