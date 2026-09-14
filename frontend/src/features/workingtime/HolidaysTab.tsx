/**
 * Calendar exceptions tab: dated overrides of the week profile, per site.
 *
 * The three cases the backend supports are all reachable here, which is why the
 * form has an hours field rather than an "is holiday" checkbox:
 *
 *   0:00                          non-working — public holiday, shutdown, bridge day
 *   below the profile             half day, as 24 and 31 December usually are
 *   above 0 on a normally free day  a designated working Saturday
 *
 * A checkbox would lose two of the three, and all three appear in real plant
 * calendars.
 */

import { useEffect, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { DataTable } from '../../components/layout'
import { showErrorNotification } from '../../utils/errorHandling'
import {
  createHoliday,
  deleteHoliday,
  updateHoliday,
  formatMinutes,
  listHolidays,
  listSites,
  parseMinutes,
  type Holiday,
  type Site,
} from '../../api/calendar'

/** ISO date of 1 January in the given year. */
function yearStart(year: number): string {
  return `${year}-01-01`
}

/** ISO date of 31 December in the given year. */
function yearEnd(year: number): string {
  return `${year}-12-31`
}

export function HolidaysTab() {
  const { t } = useTranslation()
  const currentYear = new Date().getFullYear()
  const queryClient = useQueryClient()
  const [siteId, setSiteId] = useState<string | null>(null)
  const [year, setYear] = useState(String(currentYear))
  const [modalOpen, setModalOpen] = useState(false)
  // The id being edited, or null when creating. An exception's hours are the field
  // most often wrong on first entry — a half day entered as a full non-working day —
  // so correcting it must not require deleting and re-creating the row.
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState({ day: '', name: '', hours: '0:00' })

  /**
   * The site list is SHARED with SitesTab, on the same key.
   *
   * That is the first thing this layer gives back for free: the two tabs sit on one page, and
   * previously each fetched the list itself. Now the second one is served from the cache — and, more
   * usefully, creating a site in the other tab invalidates this list too, so the dropdown here does
   * not go stale.
   */
  const sitesQuery = useQuery({
    queryKey: queryKeys.sites.list(),
    queryFn: () => listSites(),
  })
  const sites: Site[] = sitesQuery.data ?? []

  /**
   * Pick the default site once the list arrives.
   *
   * Depends on `sitesQuery.data`, NOT on the `sites` fallback above: `?? []` builds a new array on
   * every render, so an effect depending on it runs on every render. Harmless here only because the
   * `siteId !== null` guard makes the second pass a no-op — which is the kind of accident that stops
   * being harmless the moment somebody adds a line to the effect.
   */
  useEffect(() => {
    if (siteId !== null || sitesQuery.data === undefined) return
    const preferred = sitesQuery.data.find((s) => s.is_default) ?? sitesQuery.data[0]
    setSiteId(preferred?.id ?? null)
  }, [sitesQuery.data, siteId])

  /**
   * The year and the site are both IN THE KEY, so switching either cannot show the other's rows.
   *
   * The hand-written version had them as dependencies of a callback that overwrote one `holidays`
   * state. Switching year while a request was in flight could resolve the old one last — and a
   * holiday list is exactly the kind of data where nobody notices the wrong year immediately.
   */
  const holidaysQuery = useQuery({
    queryKey: [...queryKeys.capacity.holidays(siteId ?? 'none'), year],
    queryFn: () =>
      listHolidays({
        site_id: siteId as string,
        from: yearStart(Number(year)),
        to: yearEnd(Number(year)),
      }),
    enabled: siteId !== null,
  })
  const holidays: Holiday[] = holidaysQuery.data ?? []
  const loading = siteId !== null && holidaysQuery.isPending

  useEffect(() => {
    const error = sitesQuery.error ?? holidaysQuery.error
    if (error) {
      showErrorNotification(error, t('common.error'), t('workingTime.holidays.loadError'))
    }
  }, [sitesQuery.error, holidaysQuery.error, t])

  /**
   * A HOLIDAY IS CAPACITY. Declaring 3 October non-working removes a day from every resource at that
   * site, which can make an assignment stop fitting — so the finding that says so lives on the
   * dashboard, computed from data this screen just changed.
   *
   * Same four keys as the week profiles, for the same reasons. This is now the shape for anything
   * that touches available minutes.
   */
  const invalidateAfterCapacityChange = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.capacity.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
    ])
  }

  const minutesInvalid = parseMinutes(form.hours) === null

  const saveMutation = useMutation({
    mutationFn: (payload: Parameters<typeof createHoliday>[0]) =>
      editingId ? updateHoliday(editingId, payload) : createHoliday(payload),
    onSuccess: async () => {
      notifications.show({ message: t('workingTime.holidays.saved'), color: 'green' })
      setModalOpen(false)
      setEditingId(null)
      setForm({ day: '', name: '', hours: '0:00' })
      await invalidateAfterCapacityChange()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('workingTime.holidays.saveError')),
  })

  const saving = saveMutation.isPending

  const save = () => {
    if (!siteId || form.day === '' || form.name.trim() === '' || minutesInvalid) return
    saveMutation.mutate({
      site_id: siteId,
      day: form.day,
      name: form.name.trim(),
      working_minutes: parseMinutes(form.hours) ?? 0,
    })
  }

  const deleteMutation = useMutation({
    mutationFn: (holiday: Holiday) => deleteHoliday(holiday.id),
    onSuccess: async () => {
      notifications.show({ message: t('workingTime.holidays.deleted'), color: 'green' })
      await invalidateAfterCapacityChange()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('workingTime.holidays.deleteError')),
  })

  const remove = (holiday: Holiday) => {
    deleteMutation.mutate(holiday)
  }

  const yearOptions = Array.from({ length: 11 }, (_, i) => String(currentYear - 2 + i))

  return (
    <Stack gap="md">
      <Text c="dimmed" size="sm">
        {t('workingTime.holidays.hint')}
      </Text>
      <Group justify="space-between" align="flex-end">
        <Group gap="sm">
          <Select
            label={t('workingTime.holidays.site')}
            data={sites.map((s) => ({ value: s.id, label: s.name }))}
            value={siteId}
            onChange={setSiteId}
            allowDeselect={false}
            w={220}
          />
          <Select
            label={t('workingTime.holidays.year')}
            data={yearOptions}
            value={year}
            onChange={(value) => setYear(value ?? String(currentYear))}
            allowDeselect={false}
            w={120}
          />
        </Group>
        <Button
          leftSection={<IconPlus size={16} />}
          disabled={!siteId}
          onClick={() => {
            setEditingId(null)
            setForm({ day: '', name: '', hours: '0:00' })
            setModalOpen(true)
          }}
        >
          {t('workingTime.holidays.add')}
        </Button>
      </Group>

      <DataTable
        loading={loading}
        empty={holidays.length === 0}
        emptyMessage={t('workingTime.holidays.empty')}
        testId="holidays-table"
        head={
          <Table.Tr>
            <Table.Th>{t('workingTime.holidays.day')}</Table.Th>
            <Table.Th>{t('workingTime.holidays.name')}</Table.Th>
            <Table.Th>{t('workingTime.holidays.workingHours')}</Table.Th>
            <Table.Th />
          </Table.Tr>
        }
      >
        {holidays.map((holiday) => (
          <Table.Tr key={holiday.id}>
            <Table.Td>{holiday.day}</Table.Td>
            <Table.Td>{holiday.name}</Table.Td>
            <Table.Td>
              {holiday.working_minutes === 0 ? (
                <Badge color="gray">{t('workingTime.holidays.nonWorking')}</Badge>
              ) : (
                <Badge color="yellow">{formatMinutes(holiday.working_minutes)}</Badge>
              )}
            </Table.Td>
            <Table.Td>
              <Group gap="xs" justify="flex-end">
                <ActionIcon
                  variant="subtle"
                  color="blue"
                  onClick={() => {
                    setEditingId(holiday.id)
                    setForm({
                      day: holiday.day,
                      name: holiday.name,
                      hours: formatMinutes(holiday.working_minutes),
                    })
                    setModalOpen(true)
                  }}
                  aria-label={t('common.edit')}
                >
                  <IconEdit size={16} />
                </ActionIcon>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  onClick={() => void remove(holiday)}
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
        onClose={() => {
          setModalOpen(false)
          setEditingId(null)
        }}
        title={t('workingTime.holidays.add')}
      >
        <Stack gap="sm">
          <TextInput
            required
            type="date"
            label={t('workingTime.holidays.day')}
            value={form.day}
            onChange={(e) => setForm({ ...form, day: e.currentTarget.value })}
          />
          <TextInput
            required
            label={t('workingTime.holidays.name')}
            placeholder="Brückentag"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.currentTarget.value })}
          />
          <TextInput
            label={t('workingTime.holidays.workingHours')}
            description={t('workingTime.holidays.workingHoursDesc')}
            value={form.hours}
            error={minutesInvalid}
            onChange={(e) => setForm({ ...form, hours: e.currentTarget.value })}
          />
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => {
                setModalOpen(false)
                setEditingId(null)
              }}
            >
              {t('common.cancel')}
            </Button>
            <Button loading={saving} disabled={minutesInvalid} onClick={() => void save()}>
              {t('common.save')}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
