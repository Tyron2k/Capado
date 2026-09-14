/**
 * Plan baselines: freeze a plan, then see how far the live plan has moved from it.
 *
 * A baseline is a MARKER, not a lock. The page says so, because "freeze plan" reads
 * like it prevents editing — and it deliberately does not. A hard freeze would move the
 * next change into a spreadsheet, where nobody can see it at all (ADR-007).
 *
 * The drift view separates added, removed and changed rather than showing one count.
 * Work created after a freeze is genuinely new and work deleted genuinely went away;
 * folding those into "12 differences" would report normal progress as a problem.
 */

import { useEffect, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Modal,
  Paper,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Switch,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconCamera, IconInfoCircle, IconTrash } from '@tabler/icons-react'
import { DataTable, PageLayout, SectionHeader } from '../../components/layout'
import { showErrorNotification } from '../../utils/errorHandling'
import {
  createBaseline,
  deleteBaseline,
  getBaselineDiff,
  getBaselines,
  type Baseline,
  type BaselineDiff,
  type EntityDiff,
} from '../../api/baselines'
import { usePermissions } from '../../hooks/usePermissions'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'

/** Render one field's before/after pair compactly. */
function formatChange(change: { before?: unknown; after?: unknown }): string {
  return `${JSON.stringify(change.before ?? null)} → ${JSON.stringify(change.after ?? null)}`
}

function DiffSection({
  titleKey,
  color,
  entries,
  showChanges,
}: {
  titleKey: string
  color: string
  entries: EntityDiff[]
  showChanges: boolean
}) {
  const { t } = useTranslation()
  if (entries.length === 0) return null
  return (
    <Paper withBorder p="sm">
      <Group gap="xs" mb="xs">
        <Badge color={color} variant="light">
          {entries.length}
        </Badge>
        <Text fw={500} size="sm">
          {t(titleKey)}
        </Text>
      </Group>
      <Stack gap={4}>
        {entries.map((entry) => (
          <Group key={`${entry.entity_type}-${entry.entity_id}`} gap="xs" align="flex-start">
            <Text size="xs" c="dimmed" style={{ minWidth: 130 }}>
              {entry.entity_type} {entry.entity_id.slice(0, 8)}
            </Text>
            {showChanges && (
              <Stack gap={0}>
                {Object.entries(entry.changes).map(([field, change]) => (
                  <Text key={field} size="xs">
                    <Text span fw={500}>
                      {field}
                    </Text>{' '}
                    <Code>{formatChange(change)}</Code>
                  </Text>
                ))}
              </Stack>
            )}
          </Group>
        ))}
      </Stack>
    </Paper>
  )
}

export function BaselinesPage() {
  const { t } = useTranslation()
  const { isAdmin } = usePermissions()
  const queryClient = useQueryClient()
  const [diffFor, setDiffFor] = useState<Baseline | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [note, setNote] = useState('')
  const [makeCurrent, setMakeCurrent] = useState(true)
  const [pendingDelete, setPendingDelete] = useState<Baseline | null>(null)

  /**
   * A BASELINE IS A SNAPSHOT, and this is the one screen where "keep it fresh" would be WRONG.
   *
   * Everything else in this migration went stale for a reason: it described a plan that had moved. A
   * baseline describes a plan that has deliberately been frozen. It keeps saying what March looked like
   * however much March has changed since — that is what it is for. So no plan mutation touches this
   * list, and creating one invalidates only the list it was added to.
   */
  const baselinesQuery = useQuery({
    queryKey: queryKeys.baselines.list(),
    queryFn: ({ signal }) => getBaselines(signal),
  })
  const baselines: Baseline[] = baselinesQuery.data ?? []
  const loading = baselinesQuery.isPending

  useEffect(() => {
    if (baselinesQuery.error) {
      showErrorNotification(baselinesQuery.error, t('common.error'), t('baselines.loadFailed'))
    }
  }, [baselinesQuery.error, t])

  /**
   * THE DIFF IS THE EXACT OPPOSITE OF THE LIST BESIDE IT.
   *
   * It compares a frozen baseline against the plan AS IT IS NOW, so it goes stale the instant anything
   * is edited — while the baseline it is comparing must never change at all. One screen, two values with
   * opposite requirements, which is why they are separate keys rather than one baseline blob.
   *
   * `enabled` on the selected baseline replaces the `setDiff(null)` that cleared the previous one; and
   * because the diff is keyed by baseline, comparing one, then another, then the first again shows the
   * first's answer immediately instead of recomputing it.
   */
  const diffQuery = useQuery({
    queryKey: queryKeys.baselines.diff(diffFor?.id ?? 'none'),
    queryFn: () => getBaselineDiff(diffFor!.id),
    enabled: Boolean(diffFor),
  })
  const diff: BaselineDiff | null = diffQuery.data ?? null
  const diffLoading = Boolean(diffFor) && diffQuery.isPending

  useEffect(() => {
    if (diffQuery.error) {
      showErrorNotification(diffQuery.error, t('common.error'), t('baselines.diffFailed'))
    }
  }, [diffQuery.error, t])

  const showDiff = (baseline: Baseline) => {
    setDiffFor(baseline)
  }

  const createMutation = useMutation({
    mutationFn: () =>
      createBaseline({
        name: name.trim(),
        note: note.trim() || null,
        make_current: makeCurrent,
      }),
    onSuccess: async (created) => {
      // The captured row count is worth showing: it is the only signal that the freeze
      // actually caught the plan rather than an empty database.
      notifications.show({
        title: t('common.success'),
        message: t('baselines.created', { count: created.entry_count }),
        color: 'green',
      })
      setCreateOpen(false)
      setName('')
      setNote('')
      await queryClient.invalidateQueries({ queryKey: queryKeys.baselines.all })
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })
  const saving = createMutation.isPending

  const handleCreate = () => {
    if (!name.trim()) return
    createMutation.mutate()
  }

  const deleteMutation = useMutation({
    mutationFn: (baseline: Baseline) => deleteBaseline(baseline.id),
    onSuccess: async (_result, baseline) => {
      // Clearing the selection is enough to drop the diff: `enabled` turns the query off, so there is
      // no separate diff state left holding a comparison against a baseline that no longer exists.
      if (diffFor?.id === baseline.id) setDiffFor(null)
      await queryClient.invalidateQueries({ queryKey: queryKeys.baselines.all })
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const handleDelete = (baseline: Baseline) => {
    deleteMutation.mutate(baseline)
  }

  return (
    <PageLayout title={t('baselines.title')}>
      <Stack gap="md">
        {/* The single most misread thing about this feature. */}
        <Alert icon={<IconInfoCircle size={16} />} color="blue">
          {t('baselines.markerNotLock')}
        </Alert>

        <Group justify="flex-end">
          {isAdmin && (
            <Button leftSection={<IconCamera size={14} />} onClick={() => setCreateOpen(true)}>
              {t('baselines.freeze')}
            </Button>
          )}
        </Group>

        <DataTable
          loading={loading}
          empty={baselines.length === 0}
          emptyMessage={t('baselines.none')}
          head={
            <Table.Tr>
              <Table.Th>{t('common.name')}</Table.Th>
              <Table.Th>{t('baselines.createdAt')}</Table.Th>
              <Table.Th>{t('baselines.note')}</Table.Th>
              <Table.Th>{t('common.actions')}</Table.Th>
            </Table.Tr>
          }
        >
          {baselines.map((baseline) => (
            <Table.Tr key={baseline.id}>
              <Table.Td>
                <Group gap="xs">
                  <Text size="sm">{baseline.name}</Text>
                  {baseline.is_current && (
                    <Badge color="blue" variant="light">
                      {t('baselines.current')}
                    </Badge>
                  )}
                </Group>
              </Table.Td>
              <Table.Td>
                <Text size="sm">{new Date(baseline.created_at).toLocaleString()}</Text>
              </Table.Td>
              <Table.Td>
                <Text size="sm" c={baseline.note ? undefined : 'dimmed'}>
                  {baseline.note ?? '—'}
                </Text>
              </Table.Td>
              <Table.Td>
                <Group gap="xs">
                  <Button size="compact-xs" variant="light" onClick={() => showDiff(baseline)}>
                    {t('baselines.compare')}
                  </Button>
                  {isAdmin && (
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      color="red"
                      leftSection={<IconTrash size={12} />}
                      onClick={() => setPendingDelete(baseline)}
                    >
                      {t('common.delete')}
                    </Button>
                  )}
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </DataTable>

        {diffFor && (
          <Stack gap="sm">
            <SectionHeader title={t('baselines.driftAgainst', { name: diffFor.name })} />
            {diffLoading && <Text size="sm">{t('common.loading')}</Text>}
            {diff && !diff.has_drift && <Alert color="green">{t('baselines.noDrift')}</Alert>}
            {diff && diff.has_drift && (
              <>
                {/* Three sections, not one number: added work is progress, removed
                    work went away, and only "changed" means the agreed plan moved. */}
                <DiffSection
                  titleKey="baselines.changed"
                  color="orange"
                  entries={diff.changed}
                  showChanges
                />
                <DiffSection
                  titleKey="baselines.added"
                  color="green"
                  entries={diff.added}
                  showChanges={false}
                />
                <DiffSection
                  titleKey="baselines.removed"
                  color="gray"
                  entries={diff.removed}
                  showChanges={false}
                />
              </>
            )}
          </Stack>
        )}

        <Modal
          opened={createOpen}
          onClose={() => setCreateOpen(false)}
          title={t('baselines.freezeTitle')}
        >
          <Stack gap="md">
            <TextInput
              label={t('common.name')}
              description={t('baselines.nameDesc')}
              required
              value={name}
              onChange={(event) => setName(event.currentTarget.value)}
            />
            <Textarea
              label={t('baselines.note')}
              description={t('baselines.noteDesc')}
              maxLength={1000}
              value={note}
              onChange={(event) => setNote(event.currentTarget.value)}
            />
            <Switch
              label={t('baselines.makeCurrent')}
              description={t('baselines.makeCurrentDesc')}
              checked={makeCurrent}
              onChange={(event) => setMakeCurrent(event.currentTarget.checked)}
            />
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setCreateOpen(false)}>
                {t('common.cancel')}
              </Button>
              <Button onClick={handleCreate} loading={saving} disabled={!name.trim()}>
                {t('baselines.freeze')}
              </Button>
            </Group>
          </Stack>
        </Modal>

        <Modal
          opened={pendingDelete !== null}
          onClose={() => setPendingDelete(null)}
          title={t('baselines.deleteTitle')}
        >
          <Stack gap="md">
            <Text size="sm">
              {t('baselines.deleteConfirm', { name: pendingDelete?.name ?? '' })}
            </Text>
            <Text size="sm" c="dimmed">
              {t('baselines.deleteKeepsPlan')}
            </Text>
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setPendingDelete(null)}>
                {t('common.cancel')}
              </Button>
              <Button
                color="red"
                onClick={async () => {
                  if (pendingDelete) await handleDelete(pendingDelete)
                  setPendingDelete(null)
                }}
              >
                {t('common.delete')}
              </Button>
            </Group>
          </Stack>
        </Modal>
      </Stack>
    </PageLayout>
  )
}
