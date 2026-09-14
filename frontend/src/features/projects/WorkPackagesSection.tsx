/**
 * Work packages management within a project.
 * Shows work package list, create/edit form, warnings, and delete dialog.
 * Requirements: 5.1–5.6, 11.4
 */

import { useEffect, useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Modal,
  Table,
  Text,
  Title,
  Tooltip,
  Stack,
} from '@mantine/core'
import { DataTable } from '../../components/layout'
import { notifications } from '@mantine/notifications'
import { showErrorNotification } from '../../utils/errorHandling'
import {
  IconAlertTriangle,
  IconCheck,
  IconEdit,
  IconPlus,
  IconArrowsSplit2,
  IconRotate2,
  IconTrash,
} from '@tabler/icons-react'
import type { Project } from '../../types/project'
import type { WorkPackage } from '../../types/workPackage'
import {
  getWorkPackages,
  createWorkPackage,
  updateWorkPackage,
  deleteWorkPackage,
  copyRequirementsFromTemplate,
} from '../../api/workPackages'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { usePermissions } from '../../hooks/usePermissions'
import { DependencyDrawer } from './DependencyDrawer'
import { WorkPackageForm, type WorkPackageFormValues } from './WorkPackageForm'
import { getProjectSchedule } from '../../api/projects'
import { formatDate, toIsoDate } from '../../utils/date'

interface WorkPackagesSectionProps {
  project: Project
  onBack: () => void
}

export function WorkPackagesSection({ project, onBack }: WorkPackagesSectionProps) {
  const { t } = useTranslation()
  const { canWrite } = usePermissions()
  const queryClient = useQueryClient()
  const [dependencyWP, setDependencyWP] = useState<WorkPackage | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingWP, setEditingWP] = useState<WorkPackage | null>(null)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])

  const workPackagesQuery = useQuery({
    queryKey: queryKeys.projects.workPackages(project.id),
    queryFn: () => getWorkPackages(project.id),
  })
  const workPackages: WorkPackage[] = workPackagesQuery.data ?? []
  const loading = workPackagesQuery.isPending

  useEffect(() => {
    if (workPackagesQuery.error) {
      showErrorNotification(
        workPackagesQuery.error,
        t('common.error'),
        t('workPackages.loadFailed'),
      )
    }
  }, [workPackagesQuery.error, t])

  /**
   * Float per package, keyed by id. A SEPARATE query because it is DERIVED: it changes when a
   * dependency or a lead time changes, not only when a package does.
   *
   * Float is supplementary and still fails SILENTLY — the list stays usable without it, and a failed
   * analysis should not hide the work packages themselves.
   */
  const scheduleQuery = useQuery({
    queryKey: queryKeys.projects.schedule(project.id),
    queryFn: () => getProjectSchedule(project.id),
  })
  const schedule = useMemo(
    () => new Map((scheduleQuery.data?.nodes ?? []).map((n) => [n.work_package_id, n])),
    [scheduleQuery.data],
  )

  /**
   * A WORK PACKAGE IS PLAN DATA, and this is where the batch's distinction bites.
   *
   * Its dates and its lead time are what assignments hang off, what the critical path is computed
   * from, and what all three Gantt perspectives draw. A project's name is a label; a work package's
   * end date is a commitment.
   *
   * THIS FIXES A REAL STALENESS BUG. Every write here reloaded the work packages and NOTHING ELSE —
   * not the schedule, even though the float column beside each row is derived from exactly the dates
   * being edited. Moving a package's end date therefore left the float showing the slack it had
   * BEFORE the move, on the same screen, next to the new date. One coarse `projects` prefix covers the
   * list and the schedule together, so they can no longer disagree.
   *
   * The other four keys follow from what a date change means elsewhere: an assignment may no longer
   * fit inside its package (`assignments`, `conflicts`), the coverage figures move (`planning`), and
   * the digest is computed from requirements and dependencies (`digest`).
   */
  const invalidateAfterWorkPackageChange = () =>
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

  const handleCreate = () => {
    setEditingWP(null)
    setWarnings([])
    setModalOpen(true)
  }

  const handleEdit = (wp: WorkPackage) => {
    setEditingWP(wp)
    setWarnings([])
    setModalOpen(true)
  }

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteWorkPackage(project.id, id),
    onSuccess: async () => {
      notifications.show({
        title: t('common.success'),
        message: t('workPackages.workPackageDeleted'),
        color: 'green',
      })
      setDeleteConfirmId(null)
      await invalidateAfterWorkPackageChange()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const handleDelete = (id: string) => {
    deleteMutation.mutate(id)
  }

  /**
   * Complete a work package, or reopen it by passing null.
   *
   * Reopening has to stay available: a completion clicked by mistake is an ordinary
   * correction, and the audit log records both the closing and the reopening.
   */
  const completionMutation = useMutation({
    mutationFn: ({ wp, completedAt }: { wp: WorkPackage; completedAt: string | null }) =>
      updateWorkPackage(project.id, wp.id, { completed_at: completedAt }),
    onSuccess: async (_result, { completedAt }) => {
      notifications.show({
        title: t('common.success'),
        message: completedAt ? t('workPackages.markedDone') : t('workPackages.reopened'),
        color: 'green',
      })
      await invalidateAfterWorkPackageChange()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const handleCompletion = (wp: WorkPackage, completedAt: string | null) => {
    completionMutation.mutate({ wp, completedAt })
  }

  /**
   * Copying requirements from a template is NON-CRITICAL and stays so: the work package exists either
   * way, and failing the whole save because a template copy failed would be worse than a package
   * without its requirements. It is awaited inside the mutation, though, so the invalidation that
   * follows sees the copied requirements rather than racing them.
   */
  const saveMutation = useMutation({
    mutationFn: async (values: WorkPackageFormValues) => {
      const payload = {
        name: values.name.trim(),
        start_date: toIsoDate(values.start_date!),
        end_date: toIsoDate(values.end_date!),
        // Empty means "no duration claimed", which is not the same as zero.
        lead_time_working_days:
          typeof values.lead_time_working_days === 'number' ? values.lead_time_working_days : null,
      }

      if (editingWP) {
        const result = await updateWorkPackage(project.id, editingWP.id, payload)
        return { warnings: result.warnings, created: false }
      }

      const result = await createWorkPackage(project.id, payload)
      if (values.copy_template_id && result.work_package?.id) {
        try {
          await copyRequirementsFromTemplate(result.work_package.id, values.copy_template_id)
        } catch {
          // Non-critical — work package was created, requirements copy failed
        }
      }
      return { warnings: result.warnings, created: true }
    },
    onSuccess: async ({ warnings: resultWarnings, created }) => {
      notifications.show({
        title: t('common.success'),
        message: created
          ? t('workPackages.workPackageCreated')
          : t('workPackages.workPackageUpdated'),
        color: 'green',
      })
      if (resultWarnings.length > 0) {
        setWarnings(resultWarnings)
      } else {
        setModalOpen(false)
        setEditingWP(null)
      }
      await invalidateAfterWorkPackageChange()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const saving = saveMutation.isPending

  const handleSubmit = (values: WorkPackageFormValues) => {
    setWarnings([])
    saveMutation.mutate(values)
  }

  const rows = workPackages.map((wp) => (
    <Table.Tr key={wp.id}>
      <Table.Td>{wp.name}</Table.Td>
      <Table.Td>{formatDate(wp.start_date)}</Table.Td>
      <Table.Td>{formatDate(wp.end_date)}</Table.Td>
      <Table.Td>
        {wp.lead_time_working_days ?? (
          <Text size="sm" c="dimmed">
            —
          </Text>
        )}
      </Table.Td>
      <Table.Td>
        {(() => {
          const node = schedule.get(wp.id)
          if (!node) {
            return (
              <Text size="sm" c="dimmed">
                —
              </Text>
            )
          }
          return (
            <Tooltip
              label={t('workPackages.floatDetail', {
                duration: node.duration_working_days,
                earliest: formatDate(node.earliest_start),
                latest: formatDate(node.latest_start),
              })}
            >
              <Badge
                color={node.float_working_days < 0 ? 'red' : node.is_critical ? 'orange' : 'green'}
                variant="light"
                style={{ cursor: 'help' }}
              >
                {node.is_critical && node.float_working_days === 0
                  ? t('workPackages.critical')
                  : t('workPackages.floatBadge', { days: node.float_working_days })}
              </Badge>
            </Tooltip>
          )
        })()}
      </Table.Td>
      <Table.Td>
        {/* A completed package shows WHEN, not just that it is done: the timestamp is
            what a delay analysis needs, and it is already stored. */}
        {wp.completed_at ? (
          <Group gap="xs" wrap="nowrap">
            <Badge color="green" variant="light">
              {formatDate(wp.completed_at)}
            </Badge>
            {canWrite && (
              <ActionIcon
                variant="subtle"
                color="gray"
                aria-label={t('workPackages.reopen')}
                title={t('workPackages.reopen')}
                onClick={() => handleCompletion(wp, null)}
              >
                <IconRotate2 size={16} />
              </ActionIcon>
            )}
          </Group>
        ) : canWrite ? (
          <Button
            size="compact-xs"
            variant="light"
            leftSection={<IconCheck size={14} />}
            onClick={() => handleCompletion(wp, new Date().toISOString())}
          >
            {t('workPackages.markDone')}
          </Button>
        ) : (
          <Text size="sm" c="dimmed">
            —
          </Text>
        )}
      </Table.Td>
      <Table.Td>
        <Group gap="xs">
          {/* Dependencies hang on the SUCCESSOR: this is the package that waits, and the
              one whose dates a violation would ask somebody to move. */}
          <ActionIcon
            variant="subtle"
            color="grape"
            onClick={() => setDependencyWP(wp)}
            aria-label={t('dependencies.short')}
            title={t('dependencies.short')}
          >
            <IconArrowsSplit2 size={18} />
          </ActionIcon>
          <ActionIcon
            variant="subtle"
            color="blue"
            onClick={() => handleEdit(wp)}
            aria-label={t('workPackages.editAriaLabel')}
          >
            <IconEdit size={18} />
          </ActionIcon>
          <ActionIcon
            variant="subtle"
            color="red"
            data-testid={`wp-delete-${wp.id}`}
            onClick={() => setDeleteConfirmId(wp.id)}
            aria-label={t('workPackages.deleteAriaLabel')}
          >
            <IconTrash size={18} />
          </ActionIcon>
        </Group>
      </Table.Td>
    </Table.Tr>
  ))

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Group gap="sm">
          <Button variant="subtle" onClick={onBack}>
            ← {t('common.back')}
          </Button>
          <Title order={3}>{t('workPackages.title', { name: project.name })}</Title>
        </Group>
        <Button leftSection={<IconPlus size={18} />} onClick={handleCreate}>
          {t('workPackages.newWorkPackage')}
        </Button>
      </Group>

      <Text size="sm" c="dimmed">
        {t('workPackages.projectPeriod', {
          start: formatDate(project.start_date),
          end: formatDate(project.end_date),
        })}
      </Text>

      <DataTable
        loading={loading}
        empty={workPackages.length === 0}
        emptyMessage={t('workPackages.noWorkPackages')}
        head={
          <Table.Tr>
            <Table.Th>{t('common.name')}</Table.Th>
            <Table.Th>{t('workPackages.startDate')}</Table.Th>
            <Table.Th>{t('workPackages.endDate')}</Table.Th>
            <Table.Th>{t('workPackageForm.leadTime')}</Table.Th>
            <Table.Th>{t('workPackages.float')}</Table.Th>
            <Table.Th>{t('workPackages.completion')}</Table.Th>
            <Table.Th>{t('common.actions')}</Table.Th>
          </Table.Tr>
        }
      >
        {rows}
      </DataTable>

      {/* Create/Edit Modal */}
      <Modal
        opened={modalOpen}
        onClose={() => {
          setModalOpen(false)
          setEditingWP(null)
          setWarnings([])
        }}
        title={editingWP ? t('workPackages.editWorkPackage') : t('workPackages.newWorkPackage')}
        size="md"
      >
        {warnings.length > 0 && (
          <Alert
            icon={<IconAlertTriangle size={18} />}
            title={t('workPackages.hint')}
            color="yellow"
            mb="md"
            aria-live="polite"
          >
            {warnings.map((w, i) => (
              <Text key={i} size="sm">
                {w}
              </Text>
            ))}
          </Alert>
        )}
        <WorkPackageForm
          workPackage={editingWP}
          onSubmit={handleSubmit}
          onCancel={() => {
            setModalOpen(false)
            setEditingWP(null)
            setWarnings([])
          }}
          loading={saving}
        />
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        opened={deleteConfirmId !== null}
        onClose={() => setDeleteConfirmId(null)}
        title={t('workPackages.deleteWorkPackage')}
        size="sm"
      >
        <Alert icon={<IconAlertTriangle size={18} />} color="orange" mb="md">
          {t('workPackages.deleteWorkPackageCascade')}
        </Alert>
        <Text mb="lg">{t('workPackages.deleteWorkPackageConfirm')}</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={() => setDeleteConfirmId(null)}>
            {t('common.cancel')}
          </Button>
          <Button
            color="red"
            data-testid="wp-delete-confirm"
            onClick={() => deleteConfirmId && handleDelete(deleteConfirmId)}
          >
            {t('common.delete')}
          </Button>
        </Group>
      </Modal>

      <DependencyDrawer
        projectId={project.id}
        workPackage={dependencyWP}
        siblings={workPackages}
        opened={dependencyWP !== null}
        onClose={() => setDependencyWP(null)}
      />
    </Stack>
  )
}
