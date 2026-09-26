/**
 * ConflictResolutionActions — Popover with three actions per assignment
 * from a conflict card:
 *
 * - Reduce allocation (personal only)
 * - Move time range (personal: start/end date; infra: start_at/end_at)
 * - Remove assignment (DELETE)
 *
 * After each action, ``onChanged`` is called so the parent conflict view
 * reloads its data.
 */

import { useState } from 'react'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button, Divider, Group, NumberInput, Popover, Stack, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { showErrorNotification } from '../../utils/errorHandling'
import {
  IconClockMinus,
  IconCalendarEvent,
  IconTrash,
  IconDotsVertical,
  IconSwitchHorizontal,
} from '@tabler/icons-react'
import { deleteAssignment, updateAssignment } from '../../api/assignments'
import { DateField } from '../../components/DateField'
import { ZonedDateTimeField } from '../../components/ZonedDateTimeField'
import type { ConflictAssignmentInfo } from '../../types/assignment'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { useSettings } from '../../context/SettingsContext'
import { compareDates, localDateTimeToUtc, toIsoDate, type DateFormValue } from '../../utils/date'
import { AutocompleteField } from '../../components/AutocompleteField'

interface ConflictResolutionActionsProps {
  assignment: ConflictAssignmentInfo
  onChanged: () => void
}

export function ConflictResolutionActions({
  assignment,
  onChanged,
}: ConflictResolutionActionsProps) {
  const { t } = useTranslation()
  const { settings } = useSettings()
  const [bookingTimeZone] = useState(settings.timeZone)
  const queryClient = useQueryClient()
  const isPersonal =
    assignment.allocation_percent !== null && assignment.allocation_percent !== undefined
  const isInfra = assignment.start_at != null && assignment.end_at != null
  const [opened, setOpened] = useState(false)
  const [mode, setMode] = useState<'root' | 'allocation' | 'dates' | 'timestamps' | 'swap'>('root')

  const [percentValue, setPercentValue] = useState<number | ''>(assignment.allocation_percent ?? '')

  // Mantine date inputs speak `YYYY-MM-DD` / `YYYY-MM-DD HH:mm:ss` strings.
  const [startDateValue, setStartDateValue] = useState<DateFormValue>(
    assignment.start_date ? toIsoDate(assignment.start_date) : null,
  )
  const [endDateValue, setEndDateValue] = useState<DateFormValue>(
    assignment.end_date ? toIsoDate(assignment.end_date) : null,
  )

  const [startAtValue, setStartAtValue] = useState<DateFormValue>(assignment.start_at ?? null)
  const [endAtValue, setEndAtValue] = useState<DateFormValue>(assignment.end_at ?? null)

  const [swapResourceId, setSwapResourceId] = useState<string | null>(null)

  const closeAndReset = () => {
    setOpened(false)
    setMode('root')
  }

  /**
   * FIVE RESOLUTION ACTIONS, ONE INVALIDATION SET — and this file is the reason the migration's
   * measurement command cannot be trusted on its own.
   *
   * Every action here writes an assignment: reduce the allocation, move the dates, move the timestamps,
   * swap the resource, delete it. Those are the most consequential writes in the product, made from the
   * screen whose entire purpose is to fix a conflict. And the only refresh was `onChanged()` — a callback
   * whose effect depended on which parent had rendered the card, exactly like ProblemCard's before it.
   *
   * The file was never flagged as unmigrated: it has no `await get` and no `.then(`, and it tracks its
   * pending state as `setSaving` rather than `setLoading`. A grep for hand-rolled READS cannot see a file
   * that only writes. It was found by looking for hand-rolled loading flags of any spelling, which is a
   * different question and the one worth asking.
   *
   * The five handlers collapse into two mutations because they differed only in their patch and their
   * message. `onChanged()` is kept: the parent uses it to collapse the card, which is presentation.
   */
  const invalidateAfterResolution = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.assignments.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.planning.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.all }),
      // Unlike the assignments panel, the Gantt charts read this card's own subject: a conflict is
      // resolved by moving a bar, and the chart draws that bar.
      queryClient.invalidateQueries({ queryKey: queryKeys.gantt.all }),
    ])

  const resolveMutation = useMutation({
    mutationFn: ({ patch }: { patch: Record<string, unknown>; success: string; failure: string }) =>
      updateAssignment(assignment.assignment_id, patch),
    onSuccess: async (_result, { success }) => {
      notifications.show({ title: t('common.saved'), message: success, color: 'green' })
      closeAndReset()
      await invalidateAfterResolution()
      onChanged()
    },
    onError: (err, { failure }) => showErrorNotification(err, t('common.error'), failure),
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteAssignment(assignment.assignment_id),
    onSuccess: async () => {
      notifications.show({
        title: t('common.removed'),
        message: t('conflicts.assignmentDeleted'),
        color: 'green',
      })
      closeAndReset()
      await invalidateAfterResolution()
      onChanged()
    },
    onError: (err) =>
      showErrorNotification(err, t('common.error'), t('conflicts.assignmentDeleteFailed')),
  })

  const saving = resolveMutation.isPending || deleteMutation.isPending

  /** Reports a validation problem without touching the server. Kept inline: these are input mistakes. */
  const invalid = (message: string) => {
    notifications.show({ title: t('common.invalid'), message, color: 'red' })
  }

  const handleReduceAllocation = () => {
    if (typeof percentValue !== 'number' || percentValue <= 0) {
      return invalid(t('conflicts.hoursMustBePositive'))
    }
    resolveMutation.mutate({
      patch: { allocation_percent: percentValue },
      success: t('conflicts.hoursUpdated'),
      failure: t('conflicts.hoursUpdateFailed'),
    })
  }

  const handleMoveDates = () => {
    if (!startDateValue || !endDateValue) return invalid(t('conflicts.startEndRequired'))
    if (compareDates(endDateValue, startDateValue) < 0) {
      return invalid(t('conflicts.endBeforeStart'))
    }
    resolveMutation.mutate({
      patch: {
        start_date: toIsoDate(startDateValue),
        end_date: toIsoDate(endDateValue),
      },
      success: t('conflicts.periodMoved'),
      failure: t('conflicts.periodMoveFailed'),
    })
  }

  const handleMoveTimestamps = () => {
    if (!startAtValue || !endAtValue) return invalid(t('conflicts.startEndTimestampRequired'))
    const startAt = localDateTimeToUtc(startAtValue, bookingTimeZone)
    const endAt = localDateTimeToUtc(endAtValue, bookingTimeZone)
    if (!startAt || !endAt) return invalid(t('assignmentForm.validation.ambiguousTime'))
    if (Date.parse(endAt) <= Date.parse(startAt)) {
      return invalid(t('conflicts.endBeforeStartTimestamp'))
    }
    resolveMutation.mutate({
      patch: {
        start_at: startAt,
        end_at: endAt,
      },
      success: t('conflicts.periodMoved'),
      failure: t('conflicts.periodMoveFailed'),
    })
  }

  const handleDelete = () => {
    if (!window.confirm(t('conflicts.deleteConfirm'))) return
    deleteMutation.mutate()
  }

  const handleSwapResource = () => {
    if (!swapResourceId) return invalid(t('conflicts.swapSelectTarget'))
    if (swapResourceId === assignment.resource_id) {
      return invalid(t('conflicts.swapSameResource'))
    }
    resolveMutation.mutate({
      patch: { resource_id: swapResourceId },
      success: t('conflicts.swapDone'),
      failure: t('conflicts.swapFailed'),
    })
  }

  return (
    <Popover
      opened={opened}
      onChange={(value) => {
        setOpened(value)
        if (!value) setMode('root')
      }}
      position="bottom-end"
      width={360}
      withArrow
      shadow="md"
    >
      <Popover.Target>
        <Button
          size="compact-xs"
          variant="subtle"
          color="gray"
          leftSection={<IconDotsVertical size={14} />}
          data-testid="resolution-open"
          onClick={() => setOpened((s) => !s)}
          aria-label={t('conflicts.conflictActions')}
        >
          {t('common.actions')}
        </Button>
      </Popover.Target>
      <Popover.Dropdown>
        {mode === 'root' && (
          <Stack gap="xs">
            <Text size="xs" c="dimmed" mb={4}>
              {t('conflicts.resolve')}
            </Text>
            {isPersonal && (
              <Button
                size="xs"
                variant="light"
                leftSection={<IconClockMinus size={14} />}
                data-testid="resolution-reduce-open"
                onClick={() => setMode('allocation')}
                justify="start"
              >
                {t('conflicts.reduceHours')}
              </Button>
            )}
            {isPersonal && (
              <Button
                size="xs"
                variant="light"
                leftSection={<IconCalendarEvent size={14} />}
                onClick={() => setMode('dates')}
                justify="start"
              >
                {t('conflicts.moveTimeRange')}
              </Button>
            )}
            {isInfra && (
              <Button
                size="xs"
                variant="light"
                leftSection={<IconCalendarEvent size={14} />}
                onClick={() => setMode('timestamps')}
                justify="start"
              >
                {t('conflicts.moveTimeRange')}
              </Button>
            )}
            <Button
              size="xs"
              variant="light"
              leftSection={<IconSwitchHorizontal size={14} />}
              onClick={() => setMode('swap')}
              justify="start"
            >
              {t('conflicts.swapResource')}
            </Button>
            <Divider my={4} />
            <Button
              size="xs"
              variant="light"
              color="red"
              leftSection={<IconTrash size={14} />}
              data-testid="resolution-delete"
              onClick={handleDelete}
              loading={saving}
              justify="start"
            >
              {t('conflicts.removeAssignment')}
            </Button>
          </Stack>
        )}

        {mode === 'allocation' && (
          <Stack gap="xs">
            <Text size="xs" c="dimmed">
              {t('conflicts.newHoursFor', { name: assignment.work_package_name ?? '—' })}
            </Text>
            <NumberInput
              value={percentValue}
              onChange={(val) => setPercentValue(typeof val === 'number' ? val : '')}
              min={0.5}
              max={24}
              step={0.5}
              decimalScale={1}
              placeholder={t('conflicts.hoursPlaceholder')}
              size="xs"
            />
            <Group justify="flex-end" gap="xs">
              <Button variant="default" size="xs" onClick={() => setMode('root')}>
                {t('common.back')}
              </Button>
              <Button
                size="xs"
                data-testid="resolution-reduce-confirm"
                onClick={handleReduceAllocation}
                loading={saving}
              >
                {t('common.save')}
              </Button>
            </Group>
          </Stack>
        )}

        {mode === 'dates' && (
          <Stack gap="xs">
            <Text size="xs" c="dimmed">
              {t('conflicts.newPeriod')}
            </Text>
            <DateField
              label={t('common.start')}
              value={startDateValue}
              onChange={setStartDateValue}
              size="xs"
            />
            <DateField
              label={t('common.end')}
              value={endDateValue}
              onChange={setEndDateValue}
              size="xs"
            />
            <Group justify="flex-end" gap="xs">
              <Button variant="default" size="xs" onClick={() => setMode('root')}>
                {t('common.back')}
              </Button>
              <Button size="xs" onClick={handleMoveDates} loading={saving}>
                {t('common.save')}
              </Button>
            </Group>
          </Stack>
        )}

        {mode === 'timestamps' && (
          <Stack gap="xs">
            <Text size="xs" c="dimmed">
              {t('conflicts.newPeriodMinutes')}
            </Text>
            <ZonedDateTimeField
              timeZone={bookingTimeZone}
              label={t('common.start')}
              value={startAtValue}
              onChange={setStartAtValue}
              size="xs"
            />
            <ZonedDateTimeField
              timeZone={bookingTimeZone}
              label={t('common.end')}
              value={endAtValue}
              onChange={setEndAtValue}
              size="xs"
            />
            <Group justify="flex-end" gap="xs">
              <Button variant="default" size="xs" onClick={() => setMode('root')}>
                {t('common.back')}
              </Button>
              <Button size="xs" onClick={handleMoveTimestamps} loading={saving}>
                {t('common.save')}
              </Button>
            </Group>
          </Stack>
        )}

        {mode === 'swap' && (
          <Stack gap="xs">
            <Text size="xs" c="dimmed">
              {t('conflicts.swapDescription', {
                type: isPersonal ? t('conflicts.swapPersonLabel') : t('conflicts.swapInfraLabel'),
              })}
            </Text>
            <AutocompleteField
              type={isPersonal ? 'personal' : 'infrastructure'}
              label={isPersonal ? t('conflicts.swapNewPerson') : t('conflicts.swapNewInfra')}
              placeholder={
                isPersonal
                  ? t('conflicts.swapPersonPlaceholder')
                  : t('conflicts.swapInfraPlaceholder')
              }
              value={swapResourceId}
              onChange={(id) => setSwapResourceId(id)}
              noResultsMessage={t('conflicts.swapNoResult')}
            />
            <Group justify="flex-end" gap="xs">
              <Button variant="default" size="xs" onClick={() => setMode('root')}>
                {t('common.back')}
              </Button>
              <Button size="xs" onClick={handleSwapResource} loading={saving}>
                {t('conflicts.swap')}
              </Button>
            </Group>
          </Stack>
        )}
      </Popover.Dropdown>
    </Popover>
  )
}
