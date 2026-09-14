/**
 * Week profiles tab: reusable weekly patterns of available time per weekday.
 *
 * This is where part-time and shift patterns live — not in absences. A 30-hour
 * employee is not absent, and an absence has a date range rather than a weekday
 * shape, so it could never express "Mon–Thu full, Fri off".
 *
 * Hours are entered and shown as H:MM and sent as minutes. Half hours are real in
 * shift patterns, so rounding to whole hours would misreport a 7.5-hour day as 8.
 */

import { useEffect, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Modal,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Textarea,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { DataTable } from '../../components/layout'
import { showErrorNotification } from '../../utils/errorHandling'
import {
  createWorkWeekProfile,
  deleteWorkWeekProfile,
  formatMinutes,
  listWorkWeekProfiles,
  parseMinutes,
  updateWorkWeekProfile,
  type WorkWeekProfile,
} from '../../api/calendar'

/** Weekday keys in Monday-first order, matching the backend's weekday = 0..6. */
const WEEKDAYS = [
  'monday_minutes',
  'tuesday_minutes',
  'wednesday_minutes',
  'thursday_minutes',
  'friday_minutes',
  'saturday_minutes',
  'sunday_minutes',
] as const

type WeekdayKey = (typeof WEEKDAYS)[number]

interface ProfileForm {
  name: string
  description: string
  is_default: boolean
  /** Per-weekday hours as entered, e.g. "8:00". Parsed on save. */
  hours: Record<WeekdayKey, string>
}

const EMPTY_FORM: ProfileForm = {
  name: '',
  description: '',
  is_default: false,
  hours: {
    monday_minutes: '8:00',
    tuesday_minutes: '8:00',
    wednesday_minutes: '8:00',
    thursday_minutes: '8:00',
    friday_minutes: '8:00',
    saturday_minutes: '0:00',
    sunday_minutes: '0:00',
  },
}

export function WeekProfilesTab() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<WorkWeekProfile | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [form, setForm] = useState<ProfileForm>(EMPTY_FORM)

  const profilesQuery = useQuery({
    queryKey: queryKeys.capacity.weekProfiles(),
    queryFn: () => listWorkWeekProfiles(),
  })
  const profiles: WorkWeekProfile[] = profilesQuery.data ?? []
  const loading = profilesQuery.isPending

  useEffect(() => {
    if (profilesQuery.error) {
      showErrorNotification(
        profilesQuery.error,
        t('common.error'),
        t('workingTime.profiles.loadError'),
      )
    }
  }, [profilesQuery.error, t])

  /**
   * A WEEK PROFILE IS CAPACITY, so editing one can create or clear a conflict without anybody
   * touching an assignment.
   *
   * This is the first mutation where the digest invalidation is not optional. Shortening Friday on a
   * profile reduces the minutes of every resource bound to it; an assignment that fitted yesterday may
   * not fit today, and the finding that says so is computed on the dashboard from data this screen
   * just changed. The hand-written version reloaded this table of profile NAMES — the one place the
   * change was least visible.
   *
   * Four keys, and each for its own reason: this list because the row changed, resources because a
   * profile binding is shown on them, conflicts because they are derived from capacity, and the digest
   * because it is derived from the conflicts.
   */
  const invalidateAfterCapacityChange = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.capacity.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
    ])
  }

  const saveMutation = useMutation({
    mutationFn: (payload: Parameters<typeof createWorkWeekProfile>[0]) =>
      editing ? updateWorkWeekProfile(editing.id, payload) : createWorkWeekProfile(payload),
    onSuccess: async () => {
      notifications.show({ message: t('workingTime.profiles.saved'), color: 'green' })
      setModalOpen(false)
      await invalidateAfterCapacityChange()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('workingTime.profiles.saveError')),
  })

  const deleteMutation = useMutation({
    mutationFn: (profile: WorkWeekProfile) => deleteWorkWeekProfile(profile.id),
    onSuccess: async () => {
      notifications.show({ message: t('workingTime.profiles.deleted'), color: 'green' })
      await invalidateAfterCapacityChange()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('workingTime.profiles.deleteError')),
  })

  const saving = saveMutation.isPending

  const openCreate = () => {
    setEditing(null)
    setForm(EMPTY_FORM)
    setModalOpen(true)
  }

  const openEdit = (profile: WorkWeekProfile) => {
    setEditing(profile)
    setForm({
      name: profile.name,
      description: profile.description ?? '',
      is_default: profile.is_default,
      hours: WEEKDAYS.reduce(
        (acc, key) => ({ ...acc, [key]: formatMinutes(profile[key]) }),
        {} as Record<WeekdayKey, string>,
      ),
    })
    setModalOpen(true)
  }

  /** Which weekday inputs cannot be parsed. Empty means the form is valid. */
  const invalidDays = WEEKDAYS.filter((key) => parseMinutes(form.hours[key]) === null)

  const save = () => {
    if (form.name.trim() === '' || invalidDays.length > 0) return
    const minutes = WEEKDAYS.reduce(
      (acc, key) => ({ ...acc, [key]: parseMinutes(form.hours[key]) ?? 0 }),
      {} as Record<WeekdayKey, number>,
    )
    saveMutation.mutate({
      name: form.name.trim(),
      description: form.description.trim() === '' ? null : form.description.trim(),
      is_default: form.is_default,
      ...minutes,
    })
  }

  const remove = (profile: WorkWeekProfile) => {
    deleteMutation.mutate(profile)
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Text c="dimmed" size="sm">
          {t('workingTime.profiles.hint')}
        </Text>
        <Button leftSection={<IconPlus size={16} />} onClick={openCreate}>
          {t('workingTime.profiles.add')}
        </Button>
      </Group>

      <DataTable
        loading={loading}
        empty={profiles.length === 0}
        emptyMessage={t('workingTime.profiles.empty')}
        testId="profiles-table"
        head={
          <Table.Tr>
            <Table.Th>{t('workingTime.profiles.name')}</Table.Th>
            {WEEKDAYS.map((key) => (
              <Table.Th key={key}>{t(`workingTime.weekdayShort.${key}`)}</Table.Th>
            ))}
            <Table.Th>{t('workingTime.profiles.weeklyTotal')}</Table.Th>
            <Table.Th />
          </Table.Tr>
        }
      >
        {profiles.map((profile) => (
          <Table.Tr key={profile.id}>
            <Table.Td>
              <Group gap="xs">
                {profile.name}
                {profile.is_default && (
                  <Badge color="blue">{t('workingTime.profiles.default')}</Badge>
                )}
              </Group>
            </Table.Td>
            {WEEKDAYS.map((key) => (
              <Table.Td key={key}>
                <Text c={profile[key] === 0 ? 'dimmed' : undefined}>
                  {formatMinutes(profile[key])}
                </Text>
              </Table.Td>
            ))}
            <Table.Td>
              <Text fw={500}>{formatMinutes(profile.weekly_minutes)}</Text>
            </Table.Td>
            <Table.Td>
              <Group gap="xs" justify="flex-end">
                <ActionIcon
                  variant="subtle"
                  onClick={() => openEdit(profile)}
                  aria-label={t('common.edit')}
                >
                  <IconEdit size={16} />
                </ActionIcon>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  disabled={profile.is_default}
                  data-testid={`week-profile-delete-${profile.id}`}
                  onClick={() => remove(profile)}
                  aria-label={t('common.delete')}
                >
                  <IconTrash size={16} />
                </ActionIcon>
              </Group>
            </Table.Td>
          </Table.Tr>
        ))}
      </DataTable>

      <Modal
        opened={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editing ? t('workingTime.profiles.edit') : t('workingTime.profiles.add')}
      >
        <Stack gap="sm">
          <TextInput
            required
            label={t('workingTime.profiles.name')}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.currentTarget.value })}
          />
          <Textarea
            label={t('workingTime.profiles.description')}
            autosize
            minRows={2}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.currentTarget.value })}
          />
          <Text size="sm" fw={500}>
            {t('workingTime.profiles.hoursPerDay')}
          </Text>
          <Group gap="xs" grow>
            {WEEKDAYS.map((key) => (
              <TextInput
                key={key}
                label={t(`workingTime.weekdayShort.${key}`)}
                value={form.hours[key]}
                error={parseMinutes(form.hours[key]) === null}
                onChange={(e) =>
                  setForm({
                    ...form,
                    hours: { ...form.hours, [key]: e.currentTarget.value },
                  })
                }
              />
            ))}
          </Group>
          {invalidDays.length > 0 && (
            <Text size="sm" c="red">
              {t('workingTime.profiles.invalidHours')}
            </Text>
          )}
          <Switch
            label={t('workingTime.profiles.isDefault')}
            description={t('workingTime.profiles.isDefaultDesc')}
            checked={form.is_default}
            onChange={(e) => setForm({ ...form, is_default: e.currentTarget.checked })}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setModalOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button loading={saving} disabled={invalidDays.length > 0} onClick={() => void save()}>
              {t('common.save')}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
