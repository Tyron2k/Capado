/**
 * Self-contained panel for assignment CRUD operations.
 *
 * Encapsulates all assignment state management, data fetching, filtering,
 * table rendering, and modal logic. Renders a FilterBar with search input,
 * type filter select, and "New Assignment" button, followed by a DataTable
 * of filtered assignments. Includes create/edit and delete confirmation modals
 * with capacity warning display.
 */

import { useEffect, useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ActionIcon,
  Alert,
  Box,
  Button,
  Group,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core'
import { DataTable, FilterBar } from '../../components/layout'
import { notifications } from '@mantine/notifications'
import { showErrorNotification } from '../../utils/errorHandling'
import { IconAlertTriangle, IconEdit, IconPlus, IconSearch, IconTrash } from '@tabler/icons-react'
import type { Assignment, AssignmentCreate } from '../../types/assignment'
import {
  getAssignments,
  createAssignment,
  updateAssignment,
  deleteAssignment,
} from '../../api/assignments'
import { useTranslation, type Locale } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { AssignmentForm, type AssignmentFormValues } from './AssignmentForm'
import { formatDate, formatDateTime } from '../../utils/date'
import { useSettings } from '../../context/SettingsContext'
import { formatWarning, groupByProjectAndWorkPackage, toAssignmentPayload } from './assignmentUtils'

function formatAssignmentStart(assignment: Assignment, locale: Locale, timeZone: string): string {
  if (assignment.resource_type === 'personal' && assignment.start_date) {
    return formatDate(assignment.start_date)
  }
  if (assignment.start_at) {
    return formatDateTime(assignment.start_at, locale, timeZone)
  }
  return '—'
}

function formatAssignmentEnd(assignment: Assignment, locale: Locale, timeZone: string): string {
  if (assignment.resource_type === 'personal' && assignment.end_date) {
    return formatDate(assignment.end_date)
  }
  if (assignment.end_at) {
    return formatDateTime(assignment.end_at, locale, timeZone)
  }
  return '—'
}

export function AssignmentsPanel() {
  const { t } = useTranslation()
  const { settings } = useSettings()
  const queryClient = useQueryClient()
  const [modalOpen, setModalOpen] = useState(false)
  const [editingAssignment, setEditingAssignment] = useState<Assignment | null>(null)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])

  // Filter state
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<string | null>(null)
  const [projectFilter, setProjectFilter] = useState<string | null>(null)

  function formatAssignmentSize(assignment: Assignment): string {
    if (assignment.resource_type === 'personal' && assignment.allocation_percent != null) {
      return `${assignment.allocation_percent}%`
    }
    if (assignment.resource_type === 'infrastructure') {
      return '100%'
    }
    return '—'
  }

  const assignmentsQuery = useQuery({
    queryKey: queryKeys.assignments.list(),
    queryFn: ({ signal }) => getAssignments(undefined, signal),
  })
  const assignments: Assignment[] = assignmentsQuery.data ?? []
  const loading = assignmentsQuery.isPending

  useEffect(() => {
    if (assignmentsQuery.error) {
      showErrorNotification(assignmentsQuery.error, t('common.error'), t('planning.loadFailed'))
    }
  }, [assignmentsQuery.error, t])

  /**
   * WRITING AN ASSIGNMENT IS THE MOST CONSEQUENTIAL MUTATION IN THE PRODUCT.
   *
   * It decides whether a resource is overbooked (conflicts), whether a requirement is covered (the
   * digest and the planning figures), and what all three Gantt perspectives draw — and none of that is
   * on this screen. The hand-written version reloaded this table.
   *
   * `capacity` is deliberately NOT in the list: an assignment consumes capacity, it does not change
   * how much there is. Invalidating it would refetch profiles and holidays on every assignment for
   * nothing. The direction matters, and it only goes one way.
   */
  const invalidateAfterPlanChange = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.assignments.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.planning.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
      // The Gantt perspectives DRAW the dates and bars this write moves. Adding it here rather than
      // leaving each screen to remember is the same argument as the rest of this layer.
      queryClient.invalidateQueries({ queryKey: queryKeys.gantt.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.all }),
    ])
  }

  const handleCreate = () => {
    setEditingAssignment(null)
    setWarnings([])
    setModalOpen(true)
  }

  const handleEdit = (assignment: Assignment) => {
    setEditingAssignment(assignment)
    setWarnings([])
    setModalOpen(true)
  }

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteAssignment(id),
    onSuccess: async () => {
      notifications.show({
        title: t('common.success'),
        message: t('planning.assignmentDeleted'),
        color: 'green',
      })
      setDeleteConfirmId(null)
      await invalidateAfterPlanChange()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const handleDelete = (id: string) => {
    deleteMutation.mutate(id)
  }

  /**
   * A SAVE THAT SUCCEEDS WITH WARNINGS IS STILL A SAVE.
   *
   * The backend accepts an over-capacity assignment and returns warnings rather than refusing it — a
   * planner sometimes has to overbook and then fix it. So the modal stays open to show them, but the
   * data is invalidated either way: keeping the old figures on screen while the write has landed is
   * how somebody ends up acting on a number that is no longer true.
   */
  const saveMutation = useMutation({
    mutationFn: (payload: AssignmentCreate) =>
      editingAssignment
        ? updateAssignment(editingAssignment.id, payload)
        : createAssignment(payload),
    onSuccess: async (result) => {
      notifications.show({
        title: t('common.success'),
        message: editingAssignment
          ? t('planning.assignmentUpdated')
          : t('planning.assignmentCreated'),
        color: 'green',
      })
      if (result.warnings && result.warnings.length > 0) {
        setWarnings(result.warnings)
      } else {
        setModalOpen(false)
        setEditingAssignment(null)
      }
      await invalidateAfterPlanChange()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const saving = saveMutation.isPending

  const handleSubmit = (values: AssignmentFormValues) => {
    setWarnings([])
    saveMutation.mutate(toAssignmentPayload(values, settings.timeZone))
  }

  // Filter assignments based on search, type filter, and project filter
  const filteredAssignments = useMemo(() => {
    let result = assignments
    if (typeFilter) {
      result = result.filter((a) => a.resource_type === typeFilter)
    }
    if (projectFilter) {
      result = result.filter((a) => a.project_id === projectFilter)
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      result = result.filter(
        (a) =>
          (a.resource_name ?? '').toLowerCase().includes(q) ||
          (a.work_package_name ?? '').toLowerCase().includes(q) ||
          (a.project_name ?? '').toLowerCase().includes(q),
      )
    }
    return result
  }, [assignments, typeFilter, projectFilter, search])

  // Build project filter options from loaded assignments
  const projectOptions = useMemo(() => {
    const map = new Map<string, string>()
    for (const a of assignments) {
      if (a.project_id && a.project_name) {
        map.set(a.project_id, a.project_name)
      }
    }
    return Array.from(map.entries())
      .map(([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label, 'de'))
  }, [assignments])

  // Group filtered assignments by project → work package
  const groupedRows = useMemo(
    () => groupByProjectAndWorkPackage(filteredAssignments),
    [filteredAssignments],
  )

  return (
    <>
      <FilterBar>
        <TextInput
          placeholder={t('planning.searchPlaceholder')}
          leftSection={<IconSearch size={14} />}
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          style={{ minWidth: 220 }}
        />
        <Select
          placeholder={t('planning.allTypes')}
          data={[
            { value: 'personal', label: t('resources.personal') },
            { value: 'infrastructure', label: t('resources.infrastructure') },
          ]}
          value={typeFilter}
          onChange={setTypeFilter}
          clearable
          w={180}
        />
        <Select
          placeholder={t('planning.allProjects')}
          data={projectOptions}
          value={projectFilter}
          onChange={setProjectFilter}
          searchable
          clearable
          w={220}
        />
        <Button leftSection={<IconPlus size={16} />} onClick={handleCreate} size="sm" ml="auto">
          {t('planning.newAssignment')}
        </Button>
      </FilterBar>

      {loading ? (
        <DataTable
          loading={true}
          empty={false}
          head={
            <Table.Tr>
              <Table.Th />
            </Table.Tr>
          }
        >
          {null}
        </DataTable>
      ) : filteredAssignments.length === 0 ? (
        <DataTable
          empty={true}
          emptyMessage={t('planning.noAssignments')}
          head={
            <Table.Tr>
              <Table.Th />
            </Table.Tr>
          }
        >
          {null}
        </DataTable>
      ) : (
        <Stack gap="md">
          {groupedRows.map((proj) => (
            <Stack key={proj.project_id} gap="xs">
              <Text fw={600} size="sm">
                {proj.project_name}
              </Text>
              {proj.workPackages
                .sort((a, b) => a.wp_name.localeCompare(b.wp_name, 'de'))
                .map((wp) => (
                  <Box
                    key={wp.wp_id}
                    style={{
                      borderLeft: '3px solid var(--mantine-color-blue-4)',
                      paddingLeft: 12,
                    }}
                  >
                    <Text size="xs" c="dimmed" mb={4}>
                      {wp.wp_name}
                    </Text>
                    <DataTable
                      head={
                        <Table.Tr>
                          <Table.Th>{t('planning.tableType')}</Table.Th>
                          <Table.Th>{t('planning.tableResource')}</Table.Th>
                          <Table.Th>{t('planning.tableStart')}</Table.Th>
                          <Table.Th>{t('planning.tableEnd')}</Table.Th>
                          <Table.Th>{t('planning.tableScope')}</Table.Th>
                          <Table.Th style={{ width: 80 }}>{t('planning.tableActions')}</Table.Th>
                        </Table.Tr>
                      }
                    >
                      {wp.assignments.map((assignment) => (
                        <Table.Tr key={assignment.id}>
                          <Table.Td>
                            <Text size="sm">
                              {assignment.resource_type === 'personal'
                                ? t('resources.personal')
                                : t('resources.infrastructure')}
                            </Text>
                          </Table.Td>
                          <Table.Td>
                            <Group gap={4} wrap="nowrap">
                              <Text size="sm">{assignment.resource_name ?? '—'}</Text>
                              {assignment.skill_mismatch && (
                                <Tooltip label={t('planning.skillMismatch')} withArrow>
                                  <IconAlertTriangle
                                    size={14}
                                    color="var(--mantine-color-orange-6)"
                                    aria-label={t('planning.skillMismatch')}
                                  />
                                </Tooltip>
                              )}
                            </Group>
                          </Table.Td>
                          <Table.Td>
                            {formatAssignmentStart(assignment, settings.locale, settings.timeZone)}
                          </Table.Td>
                          <Table.Td>
                            {formatAssignmentEnd(assignment, settings.locale, settings.timeZone)}
                          </Table.Td>
                          <Table.Td>{formatAssignmentSize(assignment)}</Table.Td>
                          <Table.Td>
                            <Group gap="xs">
                              <ActionIcon
                                variant="subtle"
                                color="blue"
                                onClick={() => handleEdit(assignment)}
                                aria-label={t('planning.editAriaLabel')}
                              >
                                <IconEdit size={18} />
                              </ActionIcon>
                              <ActionIcon
                                variant="subtle"
                                color="red"
                                data-testid={`assignment-delete-${assignment.id}`}
                                onClick={() => setDeleteConfirmId(assignment.id)}
                                aria-label={t('planning.deleteAriaLabel')}
                              >
                                <IconTrash size={18} />
                              </ActionIcon>
                            </Group>
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </DataTable>
                  </Box>
                ))}
            </Stack>
          ))}
        </Stack>
      )}

      {/* Create/Edit Modal */}
      <Modal
        opened={modalOpen}
        onClose={() => {
          setModalOpen(false)
          setEditingAssignment(null)
          setWarnings([])
        }}
        title={editingAssignment ? t('planning.editAssignment') : t('planning.newAssignment')}
        size="md"
      >
        <Stack gap="md">
          {/* Capacity warnings (shown after save, not blocking) */}
          {warnings.length > 0 && (
            <Alert
              icon={<IconAlertTriangle size={18} />}
              title={t('planning.capacityWarning')}
              color="yellow"
              variant="light"
              aria-live="polite"
            >
              <Stack gap="xs">
                {warnings.map((warning, idx) => (
                  <Text key={idx} size="sm">
                    {formatWarning(warning, t)}
                  </Text>
                ))}
                <Text size="xs" c="dimmed" mt="xs">
                  {t('planning.capacityWarningSaved')}
                </Text>
              </Stack>
            </Alert>
          )}

          <AssignmentForm
            assignment={editingAssignment}
            onSubmit={handleSubmit}
            onCancel={() => {
              setModalOpen(false)
              setEditingAssignment(null)
              setWarnings([])
            }}
            loading={saving}
          />
        </Stack>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        opened={deleteConfirmId !== null}
        onClose={() => setDeleteConfirmId(null)}
        title={t('planning.deleteAssignment')}
        size="sm"
      >
        <Text mb="lg">{t('planning.deleteAssignmentConfirm')}</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={() => setDeleteConfirmId(null)}>
            {t('common.cancel')}
          </Button>
          <Button
            color="red"
            data-testid="assignment-delete-confirm"
            onClick={() => deleteConfirmId && handleDelete(deleteConfirmId)}
          >
            {t('common.delete')}
          </Button>
        </Group>
      </Modal>
    </>
  )
}
