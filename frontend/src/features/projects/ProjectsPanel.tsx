/**
 * Self-contained panel component for the Projects tab.
 *
 * Encapsulates project CRUD state, data fetching, folder navigation,
 * modals, and the WorkPackagesSection sub-view. Table state and presentation live in the focused ProjectsTable pilot.
 */

import { useEffect, useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Container, Grid, Group, Modal, Paper, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { showErrorNotification } from '../../utils/errorHandling'
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
import { useAuth } from '../../context/AuthContext'
import { FolderTree } from './FolderTree'
import { ProjectForm, type ProjectFormValues } from './ProjectForm'
import { WorkPackagesSection } from './WorkPackagesSection'
import { ProjectsTable } from './ProjectsTable'
import { toIsoDate } from '../../utils/date'

export function ProjectsPanel() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { canEditProject, canWrite } = usePermissions()
  const { user, refresh } = useAuth()
  const [modalOpen, setModalOpen] = useState(false)
  const [editingProject, setEditingProject] = useState<Project | null>(null)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [selectedProject, setSelectedProject] = useState<Project | null>(null)
  // null = every project regardless of grouping, 'unfiled' = those in no folder, an id
  // = that folder. None of the three is a safe default, so the selection is explicit.
  const [selectedFolder, setSelectedFolder] = useState<string | 'unfiled' | null>(null)

  const projectsQuery = useQuery({
    queryKey: queryKeys.projects.list(),
    queryFn: ({ signal }) => getProjects(signal),
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

  // Folder writes change the project lists and inherited customer metadata.
  const invalidateFolders = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.projects.all })

  // Dates and commitments drive overview/digest calculations; names appear throughout the plan.
  // Deleting a project also removes bookings and changes resource utilization.
  const invalidateProjects = (deleted = false) =>
    Promise.all(
      [
        queryKeys.projects.all,
        queryKeys.dashboard.all,
        queryKeys.digest.all,
        queryKeys.gantt.all,
        queryKeys.baselines.diffs,
        queryKeys.assignments.all,
        queryKeys.planning.all,
        queryKeys.myPlan.all,
        queryKeys.conflicts.all,
        deleted ? queryKeys.resources.all : queryKeys.resources.teamWeeks,
      ].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
    )

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
    onSuccess: () => invalidateFolders(),
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
    onSuccess: () => invalidateFolders(),
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
      // Unfiles projects and changes their inherited customer metadata.
      await invalidateFolders()
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
    // Ordered the way the backend orders them, so the sequence a planner set is what
    // they see.
    return [...result].sort((a, b) => a.position - b.position || a.name.localeCompare(b.name))
  }, [projects, selectedFolder])

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
      await invalidateProjects(true)
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
      // The backend grants access atomically; refresh the editor's local permission scopes.
      if (!editingProject && user?.role === 'editor') await refresh()
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

  if (selectedProject) {
    return (
      <Container size="xl">
        <WorkPackagesSection project={selectedProject} onBack={() => setSelectedProject(null)} />
      </Container>
    )
  }

  return (
    <>
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
          {projectsQuery.isError && (
            <Alert color="red" title={t('common.error')} mb="sm">
              {t('projects.loadFailed')}
              <Button
                variant="subtle"
                size="compact-sm"
                ml="sm"
                onClick={() => projectsQuery.refetch()}
              >
                {t('projects.retry')}
              </Button>
            </Alert>
          )}
          <ProjectsTable
            projects={filteredProjects}
            loading={loading}
            scopeKey={selectedFolder}
            canWrite={canWrite}
            canEdit={canEditProject}
            onCreate={handleCreate}
            onEdit={handleEdit}
            onDelete={setDeleteConfirmId}
            onOpen={setSelectedProject}
          />
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
