/**
 * Drawer for the operating hours of an infrastructure resource.
 *
 * Windows say WHICH CLOCK HOURS a machine, hall or track runs on which weekday — a
 * different question from a person's week profile, which asks how much of the day
 * they work. That is why infrastructure has its own model rather than reusing
 * WorkWeekProfile (ADR-005).
 *
 * Two properties of the model are easy to get wrong from a form, so both are stated
 * in the UI rather than left to be discovered:
 *
 * - A resource with NO windows is available around the clock. Adding the first window
 *   is therefore a restriction, not a relaxation, and the empty state says so.
 * - An end time before the start time means the window runs past midnight. A night
 *   shift is one row (Monday 22:00–06:00), and the tail belongs to the day the shift
 *   STARTED, so a holiday on Monday cancels the Tuesday morning hours too.
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
  TextInput,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconInfoCircle, IconMoon, IconPlus, IconTrash } from '@tabler/icons-react'
import { DataTable } from '../../components/layout'
import { showErrorNotification } from '../../utils/errorHandling'
import {
  createAvailabilityWindow,
  deleteAvailabilityWindow,
  listAvailabilityWindows,
  type AvailabilityWindow,
} from '../../api/calendar'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'

interface AvailabilityWindowsDrawerProps {
  resourceId: string
  resourceName: string
  opened: boolean
  onClose: () => void
}

/** HH:MM, the shape the API expects. Seconds are never meaningful for a shift edge. */
const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d$/

/** True when the window runs past midnight, i.e. the end is at or before the start. */
function wrapsMidnight(start: string, end: string): boolean {
  return end <= start
}

export function AvailabilityWindowsDrawer({
  resourceId,
  resourceName,
  opened,
  onClose,
}: AvailabilityWindowsDrawerProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [weekday, setWeekday] = useState<string>('0')
  const [startTime, setStartTime] = useState('06:00')
  const [endTime, setEndTime] = useState('14:00')
  const [error, setError] = useState<string | null>(null)

  // Reuses the working-time page's weekday names rather than introducing a second set
  // that could drift out of step with it.
  const weekdayNames = [
    t('workingTime.weekdayLong.monday'),
    t('workingTime.weekdayLong.tuesday'),
    t('workingTime.weekdayLong.wednesday'),
    t('workingTime.weekdayLong.thursday'),
    t('workingTime.weekdayLong.friday'),
    t('workingTime.weekdayLong.saturday'),
    t('workingTime.weekdayLong.sunday'),
  ]

  const windowsQuery = useQuery({
    queryKey: queryKeys.capacity.availabilityWindows(resourceId),
    queryFn: () => listAvailabilityWindows(resourceId),
    enabled: opened && Boolean(resourceId),
  })
  const windows: AvailabilityWindow[] = windowsQuery.data ?? []
  const loading = opened && windowsQuery.isPending

  useEffect(() => {
    if (windowsQuery.error) {
      showErrorNotification(windowsQuery.error, t('common.error'), t('windows.loadFailed'))
    }
  }, [windowsQuery.error, t])

  /**
   * AN AVAILABILITY WINDOW IS CAPACITY, and the sharpest case of it: outside its windows an
   * infrastructure resource is not bookable at all, so adding or removing one can turn a booking into
   * a window violation — a conflict cause of its own. Same four keys as the other capacity screens.
   */
  const invalidateAfterCapacityChange = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.capacity.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
    ])
  }

  const addMutation = useMutation({
    mutationFn: (payload: Parameters<typeof createAvailabilityWindow>[0]) =>
      createAvailabilityWindow(payload),
    onSuccess: async () => {
      notifications.show({
        title: t('common.success'),
        message: t('windows.created'),
        color: 'green',
      })
      await invalidateAfterCapacityChange()
    },
    onError: (err) => showErrorNotification(err, t('common.error'), t('common.unexpectedError')),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteAvailabilityWindow(id),
    onSuccess: invalidateAfterCapacityChange,
    onError: (err) => showErrorNotification(err, t('common.error'), t('common.unexpectedError')),
  })

  const saving = addMutation.isPending

  const handleAdd = () => {
    if (!TIME_PATTERN.test(startTime) || !TIME_PATTERN.test(endTime)) {
      setError(t('windows.invalidTime'))
      return
    }
    if (startTime === endTime) {
      // Rejected by the backend too. Equal times are ambiguous rather than useful:
      // they could mean "no time" or "the whole day".
      setError(t('windows.equalTimes'))
      return
    }
    setError(null)
    addMutation.mutate({
      resource_id: resourceId,
      weekday: Number(weekday),
      start_time: startTime,
      end_time: endTime,
    })
  }

  const handleDelete = (id: string) => {
    deleteMutation.mutate(id)
  }

  const sorted = [...windows].sort(
    (a, b) => a.weekday - b.weekday || a.start_time.localeCompare(b.start_time),
  )

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      title={t('windows.title', { name: resourceName })}
      position="right"
      size="lg"
    >
      <Stack gap="md">
        {windows.length === 0 && !loading && (
          // The most important sentence in this drawer: no windows means no
          // restriction, so adding the first one narrows availability.
          <Alert icon={<IconInfoCircle size={16} />} color="blue">
            {t('windows.emptyMeansAlwaysAvailable')}
          </Alert>
        )}

        <DataTable
          loading={loading}
          empty={sorted.length === 0}
          emptyMessage={t('windows.none')}
          head={
            <Table.Tr>
              <Table.Th>{t('windows.weekday')}</Table.Th>
              <Table.Th>{t('windows.from')}</Table.Th>
              <Table.Th>{t('windows.to')}</Table.Th>
              <Table.Th />
            </Table.Tr>
          }
        >
          {sorted.map((w) => (
            <Table.Tr key={w.id}>
              <Table.Td>{weekdayNames[w.weekday] ?? w.weekday}</Table.Td>
              <Table.Td>{w.start_time.slice(0, 5)}</Table.Td>
              <Table.Td>
                <Group gap="xs" wrap="nowrap">
                  <Text size="sm">{w.end_time.slice(0, 5)}</Text>
                  {wrapsMidnight(w.start_time, w.end_time) && (
                    <Badge
                      color="indigo"
                      variant="light"
                      leftSection={<IconMoon size={12} />}
                      title={t('windows.wrapsHint')}
                    >
                      {t('windows.nextDay')}
                    </Badge>
                  )}
                </Group>
              </Table.Td>
              <Table.Td ta="right">
                <ActionIcon
                  variant="subtle"
                  color="red"
                  size="sm"
                  aria-label={t('common.delete')}
                  data-testid={`window-delete-${w.id}`}
                  onClick={() => handleDelete(w.id)}
                >
                  <IconTrash size={14} />
                </ActionIcon>
              </Table.Td>
            </Table.Tr>
          ))}
        </DataTable>

        <Group align="flex-end" gap="sm">
          <Select
            label={t('windows.weekday')}
            data={weekdayNames.map((name, index) => ({
              value: String(index),
              label: name,
            }))}
            value={weekday}
            onChange={(value) => setWeekday(value ?? '0')}
            style={{ minWidth: 140 }}
          />
          <TextInput
            label={t('windows.from')}
            placeholder="06:00"
            value={startTime}
            error={error}
            onChange={(event) => setStartTime(event.currentTarget.value)}
            style={{ width: 100 }}
          />
          <TextInput
            label={t('windows.to')}
            placeholder="14:00"
            value={endTime}
            onChange={(event) => setEndTime(event.currentTarget.value)}
            style={{ width: 100 }}
          />
          <Button leftSection={<IconPlus size={14} />} loading={saving} onClick={handleAdd}>
            {t('common.add')}
          </Button>
        </Group>

        {wrapsMidnight(startTime, endTime) && startTime !== endTime && (
          <Text size="xs" c="dimmed">
            {t('windows.wrapsHint')}
          </Text>
        )}

        <Text size="xs" c="dimmed">
          {t('windows.multipleShiftsHint')}
        </Text>
      </Stack>
    </Drawer>
  )
}
