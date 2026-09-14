/**
 * The printable team week — a sheet for a wall, not a screen.
 *
 * That distinction drives every choice here. The output is a plain table with a print stylesheet
 * rather than the resource Gantt with print CSS bolted on: a Gantt answers "when does this work
 * package run", and somebody standing at a board needs "who does what on Tuesday". Reshaping one
 * into the other produces a worse version of both.
 *
 * What is deliberately NOT done:
 *
 * No sorting or grouping controls. The backend returns people by name, and a sheet whose rows move
 * from week to week is a sheet nobody can scan.
 *
 * No hover-only information. Everything that matters has to survive being printed in black and
 * white, so an overbooking is marked with a symbol as well as a colour, and absence is written as a
 * percentage rather than shaded.
 *
 * No per-person view. Individual logins were struck from this project deliberately.
 */

import { useEffect, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Group, Select, Skeleton, Stack, Text, Title } from '@mantine/core'
import { IconInfoCircle, IconPrinter } from '@tabler/icons-react'
import { getTeamWeek, type DayCell, type TeamWeek } from '../../api/teamWeek'
import { showErrorNotification } from '../../utils/errorHandling'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import './TeamWeekSheet.css'

interface TeamWeekSheetProps {
  groupId: string
  /** Selectable groups, when the caller has more than one. */
  groupOptions?: { value: string; label: string }[]
  onGroupChange?: (groupId: string) => void
}

/** Monday of the ISO week containing today, as YYYY-MM-DD. */
function isoDay(value: Date): string {
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${value.getFullYear()}-${month}-${day}`
}

function shiftWeeks(anchor: string, weeks: number): string {
  const date = new Date(`${anchor}T00:00:00`)
  date.setDate(date.getDate() + weeks * 7)
  return isoDay(date)
}

function formatDayHeader(iso: string, locale: string): string {
  const date = new Date(`${iso}T00:00:00`)
  return date.toLocaleDateString(locale, { weekday: 'short', day: '2-digit', month: '2-digit' })
}

function CellContent({ cell }: { cell: DayCell }) {
  const { t } = useTranslation()

  if (!cell.is_working_day && cell.entries.length === 0 && cell.absence_percent === 0) {
    // Marked, not blank: a blank cell reads as "nothing planned", which is a different
    // message from "the plant is closed".
    return (
      <Text size="xs" c="dimmed" ta="center">
        —
      </Text>
    )
  }

  return (
    <Stack gap={2}>
      {cell.absence_percent > 0 && (
        <Text size="xs" fw={600}>
          {t('teamWeek.absent', { percent: Math.round(cell.absence_percent) })}
          {cell.provisional_percent > 0 && ` (${t('teamWeek.provisionalShort')})`}
        </Text>
      )}
      {cell.entries.map((entry, index) => (
        <Text size="xs" key={`${entry.work_package_name}-${index}`}>
          {entry.work_package_name}
          {entry.allocation_percent < 100 && ` ${Math.round(entry.allocation_percent)}%`}
        </Text>
      ))}
      {cell.is_overbooked && (
        // A symbol as well as a colour: this has to survive black-and-white printing.
        <Text size="xs" fw={700} c="red">
          {'\u26A0'} {t('teamWeek.overbooked')}
        </Text>
      )}
    </Stack>
  )
}

export function TeamWeekSheet({ groupId, groupOptions, onGroupChange }: TeamWeekSheetProps) {
  const { t, locale } = useTranslation()
  const [anchor, setAnchor] = useState(() => isoDay(new Date()))
  /**
   * PAGING BETWEEN WEEKS IS NOW FREE THE SECOND TIME.
   *
   * The anchor is part of the key, so stepping back a week and forward again renders from cache
   * instead of re-requesting. The hand-written version refetched on every step and showed a skeleton
   * each time, which on a printable sheet somebody is flicking through is the whole interaction.
   *
   * `isPending` rather than `isFetching` for the skeleton: a revalidation of a week already on screen
   * should not blank it out.
   */
  const weekQuery = useQuery({
    queryKey: queryKeys.resources.teamWeek(groupId, anchor),
    queryFn: () => getTeamWeek(groupId, anchor),
  })
  const data: TeamWeek | null = weekQuery.data ?? null
  const loading = weekQuery.isPending

  useEffect(() => {
    if (weekQuery.error) {
      showErrorNotification(weekQuery.error, t('common.error'), t('teamWeek.loadFailed'))
    }
  }, [weekQuery.error, t])

  if (loading) {
    return (
      <Stack>
        <Skeleton height={22} width="40%" />
        <Skeleton height={220} />
      </Stack>
    )
  }

  if (!data) return null

  return (
    <Stack gap="sm">
      <Group justify="space-between" wrap="wrap" className="team-week-controls">
        <Group gap="xs">
          {groupOptions && groupOptions.length > 1 && (
            <Select
              data={groupOptions}
              value={groupId}
              onChange={(value) => value && onGroupChange?.(value)}
              allowDeselect={false}
              size="xs"
              aria-label={t('teamWeek.group')}
            />
          )}
          <Button variant="default" size="xs" onClick={() => setAnchor(shiftWeeks(anchor, -1))}>
            {t('teamWeek.previousWeek')}
          </Button>
          <Button variant="default" size="xs" onClick={() => setAnchor(isoDay(new Date()))}>
            {t('teamWeek.thisWeek')}
          </Button>
          <Button variant="default" size="xs" onClick={() => setAnchor(shiftWeeks(anchor, 1))}>
            {t('teamWeek.nextWeek')}
          </Button>
        </Group>
        <Button leftSection={<IconPrinter size={16} />} size="xs" onClick={() => window.print()}>
          {t('teamWeek.print')}
        </Button>
      </Group>

      <Title order={4}>
        {data.group_name} — {formatDayHeader(data.days[0], locale)} bis{' '}
        {formatDayHeader(data.days[data.days.length - 1], locale)}
      </Title>

      {data.rows.length === 0 ? (
        <Alert icon={<IconInfoCircle size={16} />} color="blue">
          {t('teamWeek.noPeople')}
        </Alert>
      ) : (
        // A plain table rather than a Mantine Table: print stylesheets and Mantine's scroll
        // containers fight each other, and the sheet has to paginate cleanly.
        <table className="team-week-sheet">
          <thead>
            <tr>
              <th>{t('teamWeek.person')}</th>
              {data.days.map((day) => (
                <th key={day}>{formatDayHeader(day, locale)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.resource_id}>
                <td className="team-week-name">
                  {row.name}
                  {!row.has_anything && (
                    <Text component="span" size="xs" c="dimmed">
                      {' '}
                      — {t('teamWeek.free')}
                    </Text>
                  )}
                </td>
                {row.cells.map((cell) => (
                  <td
                    key={cell.day}
                    className={
                      cell.is_working_day ? 'team-week-cell' : 'team-week-cell team-week-closed'
                    }
                  >
                    <CellContent cell={cell} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Stack>
  )
}
