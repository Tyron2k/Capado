/**
 * Audit trail viewer. Admin only.
 *
 * The log records who changed what and when, which makes it the sharpest personal-data
 * surface in Capado — behavioural data about the planners themselves. Two constraints
 * follow from that and are visible in this page rather than hidden:
 *
 * - Access is admin-only, enforced server-side. This page is not the control.
 * - Results are paged in fixed steps and the backend caps a page at 200. There is no
 *   "show all" and no export button; both would turn a traceability tool into a bulk
 *   analysis tool (ADR-006).
 *
 * The page also states the retention period, because a viewer that shows six months of
 * history without saying how long history is kept invites the assumption that it is
 * kept forever.
 */

import { useEffect, useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core'
import { IconChevronLeft, IconChevronRight, IconInfoCircle } from '@tabler/icons-react'
import { DataTable, FilterBar, PageLayout, SectionHeader } from '../../components/layout'
import { showErrorNotification } from '../../utils/errorHandling'
import {
  getAuditEntries,
  getEntityHistory,
  type AuditAction,
  type AuditEntry,
} from '../../api/audit'
import { getTenantSettings } from '../../api/settings'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { useSettings } from '../../context/SettingsContext'
import { formatDateTime } from '../../utils/date'

/** Fixed page size. Not user-configurable: a larger page is a disclosure decision. */
const PAGE_SIZE = 50

const ACTION_COLORS: Record<AuditAction, string> = {
  created: 'green',
  updated: 'blue',
  deleted: 'red',
}

/**
 * Render one field's change compactly.
 *
 * An update stores `{ before, after }`; a create stores the bare starting value. Both
 * shapes are handled because both occur, and a viewer that only understood one would
 * silently show nothing for the other.
 */
function formatChange(value: unknown): string {
  if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
    const pair = value as { before?: unknown; after?: unknown }
    if ('before' in pair || 'after' in pair) {
      return `${JSON.stringify(pair.before ?? null)} → ${JSON.stringify(pair.after ?? null)}`
    }
  }
  return JSON.stringify(value)
}

export function AuditPage() {
  const { t } = useTranslation()
  const { settings } = useSettings()
  const [offset, setOffset] = useState(0)
  const [entityType, setEntityType] = useState('')
  const [action, setAction] = useState<AuditAction | null>(null)
  const [entityId, setEntityId] = useState('')

  /**
   * FIRST SCREEN ON THE QUERY LAYER. What this replaced, and why it is the shape to copy:
   *
   * - `entries`, `loading` and a `useCallback` load function with its own `AbortController` and an
   *   `if (signal.aborted) return` after every await. All of that was correct and all of it was
   *   hand-written per screen; the library cancels a superseded request itself.
   * - The filters are IN THE KEY. They used to be dependencies of a callback that overwrote one
   *   `entries` state, so switching a filter mid-request could land the old rows under the new
   *   heading. A key per filter combination makes that impossible rather than unlikely.
   * - The retention note used to be a second `useEffect` with a swallowed `.catch()`. It is its own
   *   query now, on its own key, and it is shared with every other screen that reads settings.
   *
   * With BOTH a type and an id the dedicated history endpoint is used: it is served by the composite
   * index on (entity_type, entity_id, recorded_at), so "what happened to this one project" stays
   * cheap however large the log gets. That is why the two cases have different keys — they are
   * different requests, not one request with an extra filter.
   */
  const byEntity = entityType.trim() !== '' && entityId.trim() !== ''
  const listParams = {
    entityType: entityType.trim() || undefined,
    action: action ?? undefined,
    limit: PAGE_SIZE,
    offset,
  }

  const entriesQuery = useQuery({
    queryKey: byEntity
      ? queryKeys.audit.history(entityType.trim(), entityId.trim(), PAGE_SIZE)
      : queryKeys.audit.entries(listParams),
    queryFn: ({ signal }) =>
      byEntity
        ? getEntityHistory(entityType.trim(), entityId.trim(), PAGE_SIZE, signal)
        : getAuditEntries(
            {
              entity_type: listParams.entityType,
              action: listParams.action,
              limit: PAGE_SIZE,
              offset,
            },
            signal,
          ),
  })

  const settingsQuery = useQuery({
    queryKey: queryKeys.settings.tenant(),
    queryFn: () => getTenantSettings(),
  })

  const entries: AuditEntry[] = entriesQuery.data ?? []
  const loading = entriesQuery.isPending
  const retentionMonths = settingsQuery.data?.audit_retention_months ?? null

  /**
   * Errors are reported per screen, not by a global handler, so the message can name what failed.
   *
   * The settings query is deliberately NOT reported: the table is fully usable without the retention
   * note, and a notification about a footnote trains people to dismiss notifications.
   */
  useEffect(() => {
    if (entriesQuery.error) {
      showErrorNotification(entriesQuery.error, t('common.error'), t('audit.loadFailed'))
    }
  }, [entriesQuery.error, t])

  const actionOptions = useMemo(
    () => [
      { value: 'created', label: t('audit.actionCreated') },
      { value: 'updated', label: t('audit.actionUpdated') },
      { value: 'deleted', label: t('audit.actionDeleted') },
    ],
    [t],
  )

  // The API returns a page, not a count, so "is there a next page" is inferred from a
  // full page rather than claimed. A count query on this table would be another
  // disclosure surface for no user benefit.
  const hasNextPage = entries.length === PAGE_SIZE

  return (
    <PageLayout title={t('audit.title')}>
      <Stack gap="md">
        <Alert icon={<IconInfoCircle size={16} />} color="blue">
          <Stack gap={4}>
            <Text size="sm">{t('audit.purposeNote')}</Text>
            {retentionMonths !== null && (
              <Text size="sm">
                {retentionMonths === 0
                  ? t('audit.retentionUnlimited')
                  : t('audit.retentionNote', { months: retentionMonths })}
              </Text>
            )}
          </Stack>
        </Alert>

        <FilterBar>
          <TextInput
            label={t('audit.entityType')}
            description={t('audit.entityTypeDesc')}
            placeholder="projects"
            value={entityType}
            onChange={(event) => {
              setOffset(0)
              setEntityType(event.currentTarget.value)
            }}
            style={{ minWidth: 220 }}
          />
          <TextInput
            label={t('audit.entityId')}
            description={t('audit.entityIdDesc')}
            value={entityId}
            onChange={(event) => {
              setOffset(0)
              setEntityId(event.currentTarget.value)
            }}
            style={{ minWidth: 260 }}
          />
          <Select
            label={t('audit.action')}
            placeholder={t('audit.anyAction')}
            clearable
            data={actionOptions}
            value={action}
            onChange={(value) => {
              setOffset(0)
              setAction((value as AuditAction | null) ?? null)
            }}
            style={{ minWidth: 180 }}
          />
        </FilterBar>

        <DataTable
          loading={loading}
          empty={entries.length === 0}
          emptyMessage={t('audit.none')}
          head={
            <Table.Tr>
              <Table.Th>{t('audit.recordedAt')}</Table.Th>
              <Table.Th>{t('audit.entity')}</Table.Th>
              <Table.Th>{t('audit.action')}</Table.Th>
              <Table.Th>{t('audit.actor')}</Table.Th>
              <Table.Th>{t('audit.changes')}</Table.Th>
            </Table.Tr>
          }
        >
          {entries.map((entry) => (
            <Table.Tr key={entry.id}>
              <Table.Td>
                <Text size="sm">
                  {formatDateTime(entry.recorded_at, settings.locale, settings.timeZone, true)}
                </Text>
              </Table.Td>
              <Table.Td>
                <Stack gap={0}>
                  <Text size="sm">{entry.entity_type}</Text>
                  <Text size="xs" c="dimmed">
                    {entry.entity_id.slice(0, 8)}
                  </Text>
                </Stack>
              </Table.Td>
              <Table.Td>
                <Badge color={ACTION_COLORS[entry.action]} variant="light">
                  {t(`audit.action${entry.action[0].toUpperCase()}${entry.action.slice(1)}`)}
                </Badge>
              </Table.Td>
              <Table.Td>
                {/* Null is accurate, not missing: initial setup, scripts and token
                    refresh all write without an authenticated actor. */}
                {entry.actor_id ? (
                  <Text size="sm">{entry.actor_id.slice(0, 8)}</Text>
                ) : (
                  <Text size="sm" c="dimmed">
                    {t('audit.noActor')}
                  </Text>
                )}
              </Table.Td>
              <Table.Td>
                <Stack gap={2}>
                  {Object.entries(entry.changes).map(([field, value]) => (
                    <Text key={field} size="xs">
                      <Text span fw={500}>
                        {field}
                      </Text>{' '}
                      <Code>{formatChange(value)}</Code>
                    </Text>
                  ))}
                  {entry.reason && (
                    <Text size="xs" c="dimmed">
                      {entry.reason}
                    </Text>
                  )}
                </Stack>
              </Table.Td>
            </Table.Tr>
          ))}
        </DataTable>

        <Paper withBorder p="sm">
          <Group justify="space-between">
            <Text size="sm" c="dimmed">
              {t('audit.pageInfo', {
                from: offset + 1,
                to: offset + entries.length,
              })}
            </Text>
            <Group gap="xs">
              <Button
                variant="default"
                size="xs"
                leftSection={<IconChevronLeft size={14} />}
                disabled={offset === 0 || loading}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                {t('audit.previous')}
              </Button>
              <Button
                variant="default"
                size="xs"
                rightSection={<IconChevronRight size={14} />}
                disabled={!hasNextPage || loading}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                {t('audit.next')}
              </Button>
            </Group>
          </Group>
        </Paper>

        <SectionHeader title={t('audit.entityHistoryHint')} />
      </Stack>
    </PageLayout>
  )
}
