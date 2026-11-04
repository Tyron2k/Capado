import { Badge, Group, Paper, SimpleGrid, Stack, Table, Text } from '@mantine/core'
import { Temporal } from '@js-temporal/polyfill'
import type { Assignment, AssignmentCreate, AssignmentPreview } from '../../types/assignment'
import { useSettings } from '../../context/SettingsContext'
import { useTranslation } from '../../i18n'
import { formatDate, formatDateTime } from '../../utils/date'

interface Props {
  before?: Assignment
  after: AssignmentCreate
  preview: AssignmentPreview
  workPackageName?: string | null
  projectName?: string | null
}

/** Describe the same immutable proposal that was previewed and will be saved. */
export function AssignmentChangeSummary({
  before,
  after,
  preview,
  workPackageName,
  projectName,
}: Props) {
  const { t, locale } = useTranslation()
  const { settings } = useSettings()
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 20 })
  const resourceName = (id: string, fallback?: string | null) =>
    preview.resources.find((resource) => resource.resource_id === id)?.resource_name ||
    fallback ||
    '—'
  const instant = (value?: string | null) =>
    value
      ? `${formatDateTime(value, locale, settings.timeZone, true)} (UTC${Temporal.Instant.from(value).toZonedDateTimeISO(settings.timeZone).offset})`
      : '—'
  const duration = (booking: AssignmentCreate) =>
    booking.start_at && booking.end_at
      ? (Date.parse(booking.end_at) - Date.parse(booking.start_at)) / 60_000
      : null
  const minutes = (value: number | null) => (value === null ? '—' : `${number.format(value)} min`)
  const percent = (value?: number | null) => (value == null ? '—' : `${number.format(value)} %`)
  const rows = [
    {
      label: t('assignmentForm.resource'),
      before: before ? resourceName(before.resource_id, before.resource_name) : '—',
      after: resourceName(after.resource_id),
      changed: before?.resource_id !== after.resource_id,
    },
  ]
  if (after.resource_type === 'personal') {
    rows.push(
      {
        label: t('assignmentForm.startDate'),
        before: formatDate(before?.start_date, locale),
        after: formatDate(after.start_date, locale),
        changed: before?.start_date !== after.start_date,
      },
      {
        label: t('assignmentForm.endDate'),
        before: formatDate(before?.end_date, locale),
        after: formatDate(after.end_date, locale),
        changed: before?.end_date !== after.end_date,
      },
      {
        label: t('assignmentForm.allocation'),
        before: percent(before?.allocation_percent),
        after: percent(after.allocation_percent),
        changed: before?.allocation_percent !== after.allocation_percent,
      },
    )
  } else {
    for (const [field, label] of [
      ['start_at', 'occupiedFrom'],
      ['end_at', 'occupiedUntil'],
    ] as const) {
      rows.push({
        label: t(`assignmentForm.${label}`),
        before: instant(before?.[field]),
        after: instant(after[field]),
        changed: !before || Date.parse(before[field] ?? '') !== Date.parse(after[field] ?? ''),
      })
    }
    const beforeMinutes = before ? duration(before) : null
    const afterMinutes = duration(after)
    rows.push({
      label: t('assignmentChange.duration'),
      before: minutes(beforeMinutes),
      after: minutes(afterMinutes),
      changed: !before || beforeMinutes !== afterMinutes,
    })
  }

  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="xs">
        <Text fw={600}>
          {t(before ? 'assignmentChange.title' : 'assignmentChange.createTitle')}
        </Text>
        <Text size="sm">
          {t('assignmentForm.workPackage')}: {workPackageName ?? before?.work_package_name ?? '—'}
        </Text>
        {(projectName ?? before?.project_name) && (
          <Text size="xs" c="dimmed">
            {t('assignmentForm.project')}: {projectName ?? before?.project_name}
          </Text>
        )}
        <Text size="xs" c="dimmed">
          {t(
            after.resource_type === 'personal'
              ? 'assignmentForm.personal'
              : 'assignmentForm.infrastructure',
          )}
        </Text>
        <Stack hiddenFrom="sm" role="list" aria-label={t('assignmentChange.title')} gap="sm">
          {rows.map((row) => (
            <Stack
              key={row.label}
              role="listitem"
              gap="xs"
              style={{ borderTop: '1px solid var(--mantine-color-default-border)', paddingTop: 8 }}
            >
              <Group justify="space-between" gap="xs">
                <Text size="sm" fw={500}>
                  {row.label}
                </Text>
                <Badge size="xs" variant="light" color={row.changed ? 'blue' : 'gray'}>
                  {t(
                    !before
                      ? 'assignmentChange.new'
                      : row.changed
                        ? 'assignmentChange.changed'
                        : 'assignmentChange.unchanged',
                  )}
                </Badge>
              </Group>
              <SimpleGrid cols={2} spacing="sm">
                <Stack gap={2}>
                  <Text size="xs" c="dimmed">
                    {t('assignmentChange.before')}
                  </Text>
                  <Text size="sm" c="dimmed" style={{ overflowWrap: 'anywhere' }}>
                    {row.before}
                  </Text>
                </Stack>
                <Stack gap={2}>
                  <Text size="xs" c="dimmed">
                    {t('assignmentChange.after')}
                  </Text>
                  <Text size="sm" fw={row.changed ? 600 : 400} style={{ overflowWrap: 'anywhere' }}>
                    {row.after}
                  </Text>
                </Stack>
              </SimpleGrid>
            </Stack>
          ))}
        </Stack>
        <Table
          aria-label={t('assignmentChange.title')}
          visibleFrom="sm"
          layout="fixed"
          withTableBorder
          withColumnBorders
        >
          <Table.Thead>
            <Table.Tr>
              <Table.Th style={{ width: '30%' }}>{t('assignmentChange.field')}</Table.Th>
              <Table.Th>{t('assignmentChange.before')}</Table.Th>
              <Table.Th>{t('assignmentChange.after')}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr key={row.label}>
                <Table.Th scope="row" style={{ overflowWrap: 'anywhere' }}>
                  <Text size="xs" fw={500}>
                    {row.label}
                  </Text>
                  <Badge
                    size="xs"
                    variant="light"
                    color={row.changed ? 'blue' : 'gray'}
                    style={{ whiteSpace: 'normal', height: 'auto' }}
                  >
                    {t(
                      !before
                        ? 'assignmentChange.new'
                        : row.changed
                          ? 'assignmentChange.changed'
                          : 'assignmentChange.unchanged',
                    )}
                  </Badge>
                </Table.Th>
                <Table.Td style={{ overflowWrap: 'anywhere', verticalAlign: 'top' }}>
                  <Text size="sm" c="dimmed">
                    {row.before}
                  </Text>
                </Table.Td>
                <Table.Td style={{ overflowWrap: 'anywhere', verticalAlign: 'top' }}>
                  <Text size="sm" fw={row.changed ? 600 : 400}>
                    {row.after}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        {after.resource_type === 'infrastructure' && (
          <Text size="xs" c="dimmed">
            {t('assignmentChange.timeZone', { zone: settings.timeZone })}
          </Text>
        )}
      </Stack>
    </Paper>
  )
}
