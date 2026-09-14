/**
 * Drawer for the finish-to-start dependencies of one work package.
 *
 * Opened from the successor's row, because that is the side a violation asks somebody to
 * move: "what has to finish before this can start" is the question a planner has while
 * looking at one package.
 *
 * Two things the UI has to make plain, because neither is guessable from a form:
 *
 * - A lag of 0 means the NEXT working day, not the same day. A successor starting the day
 *   its predecessor ends would overlap it, which finish-to-start denies by definition.
 * - A dependency does not move any dates. Contradicting dates are reported, not
 *   corrected — the planner decides what to change (ADR-007's reasoning applied to
 *   scheduling).
 */

import { useEffect, useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Drawer,
  Group,
  NumberInput,
  Select,
  Stack,
  Table,
  Text,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconArrowRight, IconInfoCircle, IconPlus, IconTrash } from '@tabler/icons-react'
import { DataTable } from '../../components/layout'
import { showErrorNotification } from '../../utils/errorHandling'
import {
  createWorkPackageDependency,
  deleteWorkPackageDependency,
  getWorkPackageDependencies,
  updateWorkPackageDependencyLag,
} from '../../api/workPackages'
import type { WorkPackage, WorkPackageDependency } from '../../types/workPackage'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { formatDate } from '../../utils/date'

interface DependencyDrawerProps {
  projectId: string
  workPackage: WorkPackage | null
  /** Every work package in the project, to offer as predecessors and to resolve names. */
  siblings: WorkPackage[]
  opened: boolean
  onClose: () => void
}

export function DependencyDrawer({
  projectId,
  workPackage,
  siblings,
  opened,
  onClose,
}: DependencyDrawerProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [newPredecessor, setNewPredecessor] = useState<string | null>(null)
  const [newLag, setNewLag] = useState<number | ''>(0)

  const byId = useMemo(() => new Map(siblings.map((wp) => [wp.id, wp])), [siblings])

  /**
   * `enabled: opened` replaces the `if (opened) load()` effect, and does one thing that effect could
   * not: reopening the drawer shows the previous answer immediately while it revalidates, instead of
   * an empty list that fills in.
   */
  const dependenciesQuery = useQuery({
    queryKey: queryKeys.projects.dependencies(workPackage?.id ?? 'none'),
    queryFn: () => getWorkPackageDependencies(projectId, workPackage!.id),
    enabled: opened && Boolean(workPackage),
  })
  const predecessors: WorkPackageDependency[] = dependenciesQuery.data?.predecessors ?? []
  const successors: WorkPackageDependency[] = dependenciesQuery.data?.successors ?? []
  const loading = dependenciesQuery.isPending && dependenciesQuery.fetchStatus === 'fetching'

  useEffect(() => {
    if (dependenciesQuery.error) {
      showErrorNotification(
        dependenciesQuery.error,
        t('common.error'),
        t('dependencies.loadFailed'),
      )
    }
  }, [dependenciesQuery.error, t])

  /**
   * A DEPENDENCY IS PLAN DATA, for the same reason a work package's dates are: it decides what can
   * start when, and the float shown next to every package in the section behind this drawer is computed
   * from it.
   *
   * The hand-written version reloaded THIS DRAWER'S OWN LIST and nothing else. So adding a predecessor
   * updated the drawer, closed it, and left the float column behind it showing slack computed without
   * the dependency that had just been added — a wrong number on screen, not a missing one.
   */
  const invalidateAfterDependencyChange = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.assignments.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.planning.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
      // The Gantt perspectives DRAW the dates and bars this write moves. Adding it here rather than
      // leaving each screen to remember is the same argument as the rest of this layer.
      queryClient.invalidateQueries({ queryKey: queryKeys.gantt.all }),
    ])

  /**
   * Packages that may still be offered as a predecessor.
   *
   * Excludes the package itself and anything already linked. Does NOT try to exclude
   * every package that would close a cycle — that needs the whole graph, and the backend
   * refuses those with a message naming the reason. Offering a choice that then fails is
   * bad; silently hiding valid options because the client guessed wrong is worse.
   */
  const options = useMemo(() => {
    if (!workPackage) return []
    const linked = new Set(predecessors.map((d) => d.predecessor_id))
    return siblings
      .filter((wp) => wp.id !== workPackage.id && !linked.has(wp.id))
      .map((wp) => ({ value: wp.id, label: wp.name }))
  }, [siblings, predecessors, workPackage])

  const addMutation = useMutation({
    mutationFn: ({ predecessorId, lag }: { predecessorId: string; lag: number }) =>
      createWorkPackageDependency(projectId, workPackage!.id, predecessorId, lag),
    onSuccess: async () => {
      notifications.show({
        title: t('common.success'),
        message: t('dependencies.created'),
        color: 'green',
      })
      setNewPredecessor(null)
      setNewLag(0)
      await invalidateAfterDependencyChange()
    },
    // A cycle comes back as a business-rule error with an explanatory message; showing
    // it verbatim is more useful than a generic failure.
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const saving = addMutation.isPending

  const handleAdd = () => {
    if (!workPackage || !newPredecessor) return
    addMutation.mutate({
      predecessorId: newPredecessor,
      lag: typeof newLag === 'number' ? newLag : 0,
    })
  }

  const lagMutation = useMutation({
    mutationFn: ({ dependencyId, lag }: { dependencyId: string; lag: number }) =>
      updateWorkPackageDependencyLag(projectId, workPackage!.id, dependencyId, lag),
    onSuccess: () => invalidateAfterDependencyChange(),
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const handleLagChange = (dependencyId: string, lag: number) => {
    if (!workPackage) return
    lagMutation.mutate({ dependencyId, lag })
  }

  const deleteMutation = useMutation({
    mutationFn: (dependencyId: string) =>
      deleteWorkPackageDependency(projectId, workPackage!.id, dependencyId),
    onSuccess: () => invalidateAfterDependencyChange(),
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const handleDelete = (dependencyId: string) => {
    if (!workPackage) return
    deleteMutation.mutate(dependencyId)
  }

  const name = (id: string) => byId.get(id)?.name ?? id.slice(0, 8)
  const endDate = (id: string) => {
    const wp = byId.get(id)
    return wp ? formatDate(wp.end_date) : '—'
  }

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      title={t('dependencies.title', { name: workPackage?.name ?? '' })}
      position="right"
      size="lg"
    >
      <Stack gap="md">
        <Alert icon={<IconInfoCircle size={16} />} color="blue">
          {t('dependencies.explainer')}
        </Alert>

        <Text fw={500} size="sm">
          {t('dependencies.predecessors')}
        </Text>
        <DataTable
          loading={loading}
          empty={predecessors.length === 0}
          emptyMessage={t('dependencies.noPredecessors')}
          head={
            <Table.Tr>
              <Table.Th>{t('dependencies.mustFinish')}</Table.Th>
              <Table.Th>{t('workPackages.endDate')}</Table.Th>
              <Table.Th>{t('dependencies.lag')}</Table.Th>
              <Table.Th />
            </Table.Tr>
          }
        >
          {predecessors.map((d) => (
            <Table.Tr key={d.id}>
              <Table.Td>{name(d.predecessor_id)}</Table.Td>
              <Table.Td>{endDate(d.predecessor_id)}</Table.Td>
              <Table.Td>
                <NumberInput
                  size="xs"
                  min={0}
                  max={365}
                  allowDecimal={false}
                  allowNegative={false}
                  w={90}
                  value={d.lag_working_days}
                  onChange={(value) => typeof value === 'number' && handleLagChange(d.id, value)}
                />
              </Table.Td>
              <Table.Td ta="right">
                <ActionIcon
                  variant="subtle"
                  color="red"
                  size="sm"
                  aria-label={t('common.delete')}
                  onClick={() => handleDelete(d.id)}
                >
                  <IconTrash size={14} />
                </ActionIcon>
              </Table.Td>
            </Table.Tr>
          ))}
        </DataTable>

        <Group align="flex-end" gap="sm">
          <Select
            label={t('dependencies.addPredecessor')}
            placeholder={t('dependencies.selectPredecessor')}
            searchable
            data={options}
            value={newPredecessor}
            onChange={setNewPredecessor}
            style={{ flex: 1 }}
          />
          <NumberInput
            label={t('dependencies.lag')}
            description={t('dependencies.lagDesc')}
            min={0}
            max={365}
            allowDecimal={false}
            allowNegative={false}
            w={150}
            value={newLag}
            onChange={(value) => setNewLag(typeof value === 'number' ? value : '')}
          />
          <Button
            leftSection={<IconPlus size={14} />}
            loading={saving}
            disabled={!newPredecessor}
            onClick={handleAdd}
          >
            {t('common.add')}
          </Button>
        </Group>

        {successors.length > 0 && (
          <>
            <Text fw={500} size="sm" mt="md">
              {t('dependencies.successors')}
            </Text>
            {/* Read-only here: a link is edited from the side that waits, which is where
                the dates that would have to move live. Showing it anyway answers "what
                does delaying this break". */}
            <Stack gap={4}>
              {successors.map((d) => (
                <Group key={d.id} gap="xs">
                  <IconArrowRight size={14} />
                  <Text size="sm">{name(d.successor_id)}</Text>
                  {d.lag_working_days > 0 && (
                    <Badge size="sm" variant="light" color="gray">
                      {t('dependencies.lagBadge', { days: d.lag_working_days })}
                    </Badge>
                  )}
                </Group>
              ))}
            </Stack>
          </>
        )}
      </Stack>
    </Drawer>
  )
}
