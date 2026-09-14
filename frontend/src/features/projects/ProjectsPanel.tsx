/**
 * Self-contained panel component for the Projects tab.
 *
 * Encapsulates all project CRUD state, data fetching, table rendering,
 * modals, and the WorkPackagesSection sub-view. Renders a FilterBar with
 * a search input and "New Project" button as the first content element.
 * Implements client-side search filtering on the projects list (case-insensitive by name).
 */

import { useEffect, useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ActionIcon,
  Button,
  Container,
  Grid,
  Group,
  Modal,
  Paper,
  Table,
  Text,
  TextInput,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { showErrorNotification } from '../../utils/errorHandling'
import { IconEdit, IconTrash, IconPlus, IconPackage, IconSearch } from '@tabler/icons-react'
import type { Project, ProjectCreate, ProjectFolder } from '../../types/project'
import {
  createProject,
  createProjectFolder,
  deleteProject,
  deleteProjectFolder,
  getProjectFolders,
  getProjects,
  updateProject,
  updateProjectFolder,
} from '../../api/projects'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { usePermissions } from '../../hooks/usePermissions'
import { FolderTree } from './FolderTree'
import { ProjectForm, type ProjectFormValues } from './ProjectForm'
import { WorkPackagesSection } from './WorkPackagesSection'
import { DataTable, FilterBar } from '../../components/layout'
import { formatDate, toIsoDate } from '../../utils/date'

export function ProjectsPanel() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { canEditProject, canWrite } = usePermissions()
  const [modalOpen, setModalOpen] = useState(false)
  const [editingProject, setEditingProject] = useState<Project | null>(null)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [selectedProject, setSelectedProject] = useState<Project | null>(null)
  const [search, setSearch] = useState('')
  // null = every project regardless of grouping, 'unfiled' = those in no folder, an id
  // = that folder. None of the three is a safe default, so the selection is explicit.
  const [selectedFolder, setSelectedFolder] = useState<string | 'unfiled' | null>(null)

  const projectsQuery = useQuery({
    queryKey: queryKeys.projects.list(),
    queryFn: () => getProjects(),
  })
  const projects: Project[] = projectsQuery.data ?? []
  const loading = projectsQuery.isPending

  const foldersQuery = useQuery({
    queryKey: queryKeys.projects.folders(),
    queryFn: ({ signal }) => getProjectFolders(signal),
  })
  const folders: ProjectFolder[] = foldersQuery.data ?? []

  useEffect(() => {
    if (projectsQuery.error) {
      showErrorNotification(projectsQuery.error, t('common.error'), t('projects.loadFailed'))
    }
  }, [projectsQuery.error, t])

  useEffect(() => {
    if (foldersQuery.error) {
      showErrorNotification(foldersQuery.error, t('common.error'), t('folders.loadFailed'))
    }
  }, [foldersQuery.error, t])

  /**
   * PROJECT MASTER DATA DOES NOT CHANGE THE PLAN.
   *
   * A project's name, folder, customer, reference and priority are labels and structure. Nothing about
   * how much work is committed to whom changes when they do — which is why this invalidates `projects`
   * and stops, where an assignment invalidates five keys. The distinction is the whole reason work
   * packages and projects are separate kinds in the key tree.
   *
   * Dates are the exception in principle, and are handled where they have consequences: a work
   * package's dates drive the schedule, and WorkPackagesSection invalidates accordingly. A project's
   * own dates are the envelope the packages sit in, and the backend derives nothing from them alone.
   *
   * ONE COARSE PREFIX COVERS THE FOLDER COUPLING FOR FREE. Deleting a folder unfiles the projects
   * inside it, so the hand-written version had to remember to reload BOTH lists — one call did folders,
   * one did projects, and getting it right depended on noticing. Folders and projects both live under
   * `['projects', ...]`, so the coarse prefix invalidates both whether or not anyone remembered.
   */
  const invalidateProjects = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.projects.all })

  /**
   * Projects per folder, for the counts in the tree.
   *
   * Counted from the full list rather than fetched per folder: the list is already
   * loaded, and one request per folder would scale with how deeply the user nests.
   */
  const projectCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const project of projects) {
      if (project.folder_id) counts[project.folder_id] = (counts[project.folder_id] ?? 0) + 1
    }
    return counts
  }, [projects])

  const folderCreateMutation = useMutation({
    mutationFn: (input: {
      name: string
      parent_id: string | null
      position: number
      external_ref: string | null
      customer_id: string | null
    }) => createProjectFolder(input),
    onSuccess: () => invalidateProjects(),
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const handleFolderCreate = (
    name: string,
    parentId: string | null,
    position: number,
    // Must be declared explicitly. TypeScript accepts a handler with FEWER parameters
    // than the prop type promises, so leaving this off compiled cleanly and silently
    // dropped whatever the user typed into the order-number field.
    externalRef: string | null,
    // Same reason as above, and it happened again: the customer field was added to the dialog
    // and this handler compiled unchanged, silently discarding it.
    customerId: string | null,
  ) => {
    return folderCreateMutation
      .mutateAsync({
        name,
        parent_id: parentId,
        position,
        external_ref: externalRef,
        customer_id: customerId,
      })
      .then(() => undefined)
  }

  const folderUpdateMutation = useMutation({
    mutationFn: ({
      id,
      patch,
    }: {
      id: string
      // Lists every field the tree can send, even though `patch` is forwarded whole and
      // an extra key would arrive regardless. A narrower type here compiles fine — it is
      // a supertype of what the caller passes — and would quietly become wrong the moment
      // somebody destructures instead of forwarding.
      patch: {
        name?: string
        parent_id?: string | null
        position?: number
        external_ref?: string | null
        customer_id?: string | null
      }
    }) => updateProjectFolder(id, patch),
    onSuccess: () => invalidateProjects(),
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const handleFolderUpdate = (
    id: string,
    patch: {
      name?: string
      parent_id?: string | null
      position?: number
      external_ref?: string | null
      customer_id?: string | null
    },
  ) => folderUpdateMutation.mutateAsync({ id, patch }).then(() => undefined)

  const folderDeleteMutation = useMutation({
    mutationFn: (id: string) => deleteProjectFolder(id),
    onSuccess: async (result, id) => {
      // Say what happened. The user just clicked delete on something their projects
      // were in, so silence would leave them wondering where those went.
      notifications.show({
        title: t('common.success'),
        message: t('folders.deleted', {
          projects: result.projects_unfiled,
          subfolders: result.subfolders_moved,
        }),
        color: 'green',
      })
      if (selectedFolder === id) setSelectedFolder(null)
      // Unfiles the projects inside it. One coarse prefix covers both lists — see invalidateProjects.
      await invalidateProjects()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const handleFolderDelete = (id: string) =>
    folderDeleteMutation.mutateAsync(id).then(() => undefined)

  // The tree disables its controls while any folder write is in flight, so all three count.
  const folderBusy =
    folderCreateMutation.isPending ||
    folderUpdateMutation.isPending ||
    folderDeleteMutation.isPending

  const filteredProjects = useMemo(() => {
    let result = projects
    if (selectedFolder === 'unfiled') {
      result = result.filter((p) => p.folder_id === null)
    } else if (selectedFolder !== null) {
      result = result.filter((p) => p.folder_id === selectedFolder)
    }
    if (search.trim()) {
      const term = search.trim().toLowerCase()
      // Searching the external reference too: the plant identifies a unit by its
      // external reference far more often than by the name someone typed.
      result = result.filter(
        (p) =>
          p.name.toLowerCase().includes(term) ||
          (p.external_ref ?? '').toLowerCase().includes(term),
      )
    }
    // Ordered the way the backend orders them, so the sequence a planner set is what
    // they see.
    return [...result].sort((a, b) => a.position - b.position || a.name.localeCompare(b.name))
  }, [projects, search, selectedFolder])

  const handleCreate = () => {
    setEditingProject(null)
    setModalOpen(true)
  }

  const handleEdit = (project: Project) => {
    setEditingProject(project)
    setModalOpen(true)
  }

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteProject(id),
    onSuccess: async () => {
      notifications.show({
        title: t('common.success'),
        message: t('projects.projectDeleted'),
        color: 'green',
      })
      setDeleteConfirmId(null)
      await invalidateProjects()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const handleDelete = (id: string) => {
    deleteMutation.mutate(id)
  }

  const saveMutation = useMutation({
    mutationFn: (payload: ProjectCreate) =>
      editingProject ? updateProject(editingProject.id, payload) : createProject(payload),
    onSuccess: async () => {
      notifications.show({
        title: t('common.success'),
        message: editingProject ? t('projects.projectUpdated') : t('projects.projectCreated'),
        color: 'green',
      })
      setModalOpen(false)
      setEditingProject(null)
      await invalidateProjects()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const saving = saveMutation.isPending

  const handleSubmit = (values: ProjectFormValues) => {
    saveMutation.mutate({
      name: values.name.trim(),
      start_date: toIsoDate(values.start_date!),
      end_date: toIsoDate(values.end_date!),
      folder_id: values.folder_id,
      position: values.position,
      // Blank means "no reference", and null is the single representation of that.
      external_ref: values.external_ref.trim() || null,
      // Empty means nothing was promised. Null is the single representation of that,
      // and it is deliberately different from "promised for the planned end".
      committed_delivery_date: values.committed_delivery_date
        ? toIsoDate(values.committed_delivery_date)
        : null,
      // Blank means internal work. Null is the single representation of that.
      customer_id: values.customer_id,
      priority: values.priority,
    })
  }

  const rows = filteredProjects.map((project) => (
    <Table.Tr key={project.id}>
      <Table.Td>{project.name}</Table.Td>
      <Table.Td>
        {project.external_ref ?? (
          <Text size="sm" c="dimmed">
            —
          </Text>
        )}
      </Table.Td>
      <Table.Td>{formatDate(project.start_date)}</Table.Td>
      <Table.Td>{formatDate(project.end_date)}</Table.Td>
      <Table.Td>
        <Group gap="xs">
          <ActionIcon
            variant="subtle"
            color="teal"
            onClick={() => setSelectedProject(project)}
            aria-label={t('projects.workPackagesAriaLabel')}
            title={t('projects.workPackagesTitle')}
          >
            <IconPackage size={18} />
          </ActionIcon>
          {canEditProject(project.id) && (
            <ActionIcon
              variant="subtle"
              color="blue"
              onClick={() => handleEdit(project)}
              aria-label={t('projects.editAriaLabel')}
            >
              <IconEdit size={18} />
            </ActionIcon>
          )}
          {canEditProject(project.id) && (
            <ActionIcon
              variant="subtle"
              color="red"
              data-testid={`project-delete-${project.id}`}
              onClick={() => setDeleteConfirmId(project.id)}
              aria-label={t('projects.deleteAriaLabel')}
            >
              <IconTrash size={18} />
            </ActionIcon>
          )}
        </Group>
      </Table.Td>
    </Table.Tr>
  ))

  if (selectedProject) {
    return (
      <Container size="xl">
        <WorkPackagesSection project={selectedProject} onBack={() => setSelectedProject(null)} />
      </Container>
    )
  }

  return (
    <>
      <FilterBar>
        <TextInput
          placeholder={t('projects.searchPlaceholder')}
          leftSection={<IconSearch size={14} />}
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          style={{ minWidth: 260 }}
        />
        {canWrite && (
          <Button leftSection={<IconPlus size={14} />} onClick={handleCreate} size="sm" ml="auto">
            {t('projects.newProject')}
          </Button>
        )}
      </FilterBar>

      {/* Folders on the left, the filtered list on the right. The tree stays visible
          even with no folders defined, because that is how a user discovers grouping
          exists at all — a feature reachable only from a menu nobody opens is the same
          as no feature. */}
      <Grid>
        <Grid.Col span={{ base: 12, md: 3 }}>
          <Paper withBorder p="sm">
            <FolderTree
              folders={folders}
              projectCounts={projectCounts}
              selectedId={selectedFolder}
              onSelect={setSelectedFolder}
              onCreate={handleFolderCreate}
              onUpdate={handleFolderUpdate}
              onDelete={handleFolderDelete}
              busy={folderBusy}
            />
          </Paper>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 9 }}>
          <DataTable
            loading={loading}
            empty={filteredProjects.length === 0}
            emptyMessage={t('projects.noProjects')}
            head={
              <Table.Tr>
                <Table.Th>{t('common.name')}</Table.Th>
                <Table.Th>{t('projectForm.externalRef')}</Table.Th>
                <Table.Th>{t('projects.startDate')}</Table.Th>
                <Table.Th>{t('projects.endDate')}</Table.Th>
                <Table.Th>{t('common.actions')}</Table.Th>
              </Table.Tr>
            }
          >
            {rows}
          </DataTable>
        </Grid.Col>
      </Grid>

      {/* Create/Edit Modal */}
      <Modal
        opened={modalOpen}
        onClose={() => {
          setModalOpen(false)
          setEditingProject(null)
        }}
        title={editingProject ? t('projects.editProject') : t('projects.newProject')}
        size="md"
      >
        <ProjectForm
          project={editingProject}
          folders={folders}
          defaultFolderId={selectedFolder === 'unfiled' ? null : selectedFolder}
          onSubmit={handleSubmit}
          onCancel={() => {
            setModalOpen(false)
            setEditingProject(null)
          }}
          loading={saving}
        />
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        opened={deleteConfirmId !== null}
        onClose={() => setDeleteConfirmId(null)}
        title={t('projects.deleteProject')}
        size="sm"
      >
        <Text mb="lg">{t('projects.deleteProjectConfirm')}</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={() => setDeleteConfirmId(null)}>
            {t('common.cancel')}
          </Button>
          <Button
            color="red"
            data-testid="project-delete-confirm"
            onClick={() => deleteConfirmId && handleDelete(deleteConfirmId)}
          >
            {t('common.delete')}
          </Button>
        </Group>
      </Modal>
    </>
  )
}
