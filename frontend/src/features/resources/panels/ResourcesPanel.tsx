import { ResourcesTable } from '../ResourcesTable'
/**
 * Unified resources panel for both personal and infrastructure resources.
 * Keeps resource forms, permissions, drawers and cache invalidation around the typed table.
 * Group assignment is managed via the edit form only.
 */

import { useEffect, useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ActionIcon, Button, Group, Modal, Text, Tooltip } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { showErrorNotification } from '../../../utils/errorHandling'
import { useNavigate } from 'react-router-dom'
import { listSites } from '../../../api/calendar'
import {
  IconCalendarOff,
  IconCertificate,
  IconClockHour4,
  IconEdit,
  IconTrash,
} from '@tabler/icons-react'
import type { Resource, ResourceCreate, ResourceListItem } from '../../../types/resource'
import {
  createPersonalResource,
  createInfrastructureResource,
  deletePersonalResource,
  deleteInfrastructureResource,
  getPersonalResource,
  getInfrastructureResource,
  getPersonalTree,
  getInfrastructureTree,
  updatePersonalResource,
  updateInfrastructureResource,
} from '../../../api/resources'
import { useTranslation } from '../../../i18n'
import { queryKeys } from '../../../api/queryClient'
import { usePermissions } from '../../../hooks/usePermissions'
import { ResourceForm } from '../ResourceForm'
import { SkillMatrixDrawer } from '../SkillMatrixDrawer'
import { AbsenceDrawer } from '../AbsenceDrawer'
import { AvailabilityWindowsDrawer } from '../AvailabilityWindowsDrawer'
import { WorkProfileDrawer } from '../WorkProfileDrawer'
import { flattenResourceList, type FlatResource } from '../utils/resourceTableUtils'

interface ResourcesPanelProps {
  /** Determines which API endpoints and groups to use. */
  resourceType: 'personal' | 'infrastructure'
}

/**
 * User-facing labels are per entity type, not shared.
 *
 * This panel serves BOTH people and machines, and used to word every label
 * "Ressource" so one string could cover both. Calling a person a resource is
 * exactly the language the data-protection concept works against, so each label
 * now names what it is actually showing.
 *
 * Most of these keys ALREADY EXISTED (newPerson, editPerson, infraUpdated,
 * personalTreeError, …) and no caller used them — the split was half-built and
 * the panel kept reaching for the generic wording. Reused rather than replaced.
 *
 * Separate keys rather than one key with an `{entity}` placeholder: German
 * inflects the article and adjective with the noun's gender — "Neue Person" but
 * "Neues Infrastrukturobjekt" — so an interpolated entity name produces wrong
 * German for one of the two types.
 */
const LABEL_KEYS = {
  personal: {
    new: 'resources.newPerson',
    edit: 'resources.editPerson',
    deactivate: 'resources.deactivatePerson',
    deactivateConfirm: 'resources.deactivatePersonConfirm',
    search: 'resources.searchPersonPlaceholder',
    empty: 'resources.noPeople',
    loadFailed: 'resources.personalTreeError',
    created: 'resources.personCreated',
    updated: 'resources.personUpdated',
    deactivated: 'resources.personDeactivated',
  },
  infrastructure: {
    new: 'resources.newInfraResource',
    edit: 'resources.editInfraResource',
    deactivate: 'resources.deactivateResource',
    deactivateConfirm: 'resources.deactivateResourceConfirm',
    search: 'resources.searchInfraPlaceholder',
    empty: 'resources.noInfrastructure',
    loadFailed: 'resources.infraTreeError',
    created: 'resources.infraCreated',
    updated: 'resources.infraUpdated',
    deactivated: 'resources.infraDeactivated',
  },
} as const

export function ResourcesPanel({ resourceType }: ResourcesPanelProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const labels = LABEL_KEYS[resourceType]
  const navigate = useNavigate()
  const { canEditGroup, canWrite } = usePermissions()
  const [editingResource, setEditingResource] = useState<Resource | null>(null)
  const [deletingResource, setDeletingResource] = useState<Resource | null>(null)
  const [skillResource, setSkillResource] = useState<Resource | null>(null)
  const [absenceResource, setAbsenceResource] = useState<Resource | null>(null)
  // Only id and name are needed, and the table row is a FlatResource — narrowing to
  // that avoids widening the row type just to open a drawer.
  const [windowResource, setWindowResource] = useState<{ id: string; name: string } | null>(null)
  const [profileResource, setProfileResource] = useState<{
    id: string
    name: string
    group_id: string | null
  } | null>(null)
  // Whether the INSTALLATION has sites, not whether the loaded rows use one. Deriving it from the
  // rows would hide the column exactly while an operator is assigning the first ones, which is when
  // they need the feedback. Same rule as the resource form.

  const [formOpened, { open: openForm, close: closeForm }] = useDisclosure(false)
  const [deleteOpened, { open: openDelete, close: closeDelete }] = useDisclosure(false)

  // Select API functions based on resource type
  const api = useMemo(
    () =>
      resourceType === 'personal'
        ? {
            getList: getPersonalTree,
            getOne: getPersonalResource,
            create: createPersonalResource,
            update: updatePersonalResource,
            remove: deletePersonalResource,
          }
        : {
            getList: getInfrastructureTree,
            getOne: getInfrastructureResource,
            create: createInfrastructureResource,
            update: updateInfrastructureResource,
            remove: deleteInfrastructureResource,
          },
    [resourceType],
  )

  /**
   * The resource type IS IN THE KEY, so the people list and the infrastructure list are separate cache
   * entries. They come from different endpoints via `api`, and one tab must never render the other's
   * rows because it mounted first.
   */
  const resourcesQuery = useQuery({
    queryKey: queryKeys.resources.list(resourceType, false),
    queryFn: ({ signal }) => api.getList(signal),
  })
  const resources: ResourceListItem[] = useMemo(
    () => resourcesQuery.data ?? [],
    [resourcesQuery.data],
  )
  const loading = resourcesQuery.isPending

  useEffect(() => {
    if (resourcesQuery.error) {
      showErrorNotification(resourcesQuery.error, t('common.error'), t(labels.loadFailed))
    }
  }, [resourcesQuery.error, labels.loadFailed, t])

  /**
   * Whether the installation has sites at all, which decides if the site column exists.
   *
   * Shares `sites.list()` with SitesTab and the resource form, so creating the first site makes the
   * column appear without a reload. Previously this was read once on mount, so a single-plant operator
   * who set up their first site went on seeing no site column until they navigated away and back.
   */
  const sitesQuery = useQuery({
    queryKey: queryKeys.sites.list(),
    queryFn: () => listSites(),
  })
  const hasSites = (sitesQuery.data?.length ?? 0) > 0

  /**
   * A RESOURCE IS A PARTICIPANT IN THE PLAN, not a label on it.
   *
   * Deactivating a person does not delete their assignments, but it changes whether those assignments
   * can be honoured — which is a conflict and a digest finding. Renaming one changes what every
   * assignment row, conflict card and week sheet displays. The hand-written version refreshed this
   * table alone.
   */
  const invalidateAfterResourceChange = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.assignments.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
      // The Gantt perspectives DRAW the dates and bars this write moves. Adding it here rather than
      // leaving each screen to remember is the same argument as the rest of this layer.
      queryClient.invalidateQueries({ queryKey: queryKeys.gantt.all }),
    ])

  const flatResources = useMemo(() => flattenResourceList(resources), [resources])
  const handleCreate = () => {
    setEditingResource(null)
    openForm()
  }

  const handleEdit = async (resource: FlatResource) => {
    try {
      const full = await api.getOne(resource.id)
      setEditingResource(full)
      openForm()
    } catch (error: unknown) {
      showErrorNotification(error, t('common.error'), t(labels.loadFailed))
    }
  }

  const handleDeleteClick = async (resource: FlatResource) => {
    try {
      const full = await api.getOne(resource.id)
      setDeletingResource(full)
      openDelete()
    } catch (error: unknown) {
      showErrorNotification(error, t('common.error'), t(labels.loadFailed))
    }
  }

  const handleSkill = async (resource: FlatResource) => {
    try {
      const full = await api.getOne(resource.id)
      setSkillResource(full)
    } catch (error: unknown) {
      showErrorNotification(error, t('common.error'), t(labels.loadFailed))
    }
  }

  const handleAbsence = async (resource: FlatResource) => {
    try {
      const full = await api.getOne(resource.id)
      setAbsenceResource(full)
    } catch (error: unknown) {
      showErrorNotification(error, t('common.error'), t(labels.loadFailed))
    }
  }

  const saveMutation = useMutation({
    mutationFn: (values: ResourceCreate) =>
      editingResource ? api.update(editingResource.id, values) : api.create(values),
    onSuccess: async (_result, values) => {
      notifications.show({
        title: editingResource ? t('common.saved') : t('common.created'),
        message: editingResource
          ? t(labels.updated, { name: values.name })
          : t(labels.created, { name: values.name }),
        color: 'green',
      })
      closeForm()
      await invalidateAfterResourceChange()
    },
    onError: (error) => showErrorNotification(error, t('common.error'), t('common.saveFailed')),
  })

  const handleSubmit = (values: ResourceCreate) => {
    saveMutation.mutate(values)
  }

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.remove(id),
    onSuccess: async () => {
      notifications.show({
        title: t('common.deleted'),
        message: t(labels.deactivated, { name: deletingResource?.name ?? '' }),
        color: 'green',
      })
      closeDelete()
      setDeletingResource(null)
      await invalidateAfterResourceChange()
    },
    onError: (error) => showErrorNotification(error, t('common.error'), t('common.deleteFailed')),
  })

  const handleDelete = () => {
    if (!deletingResource) return
    deleteMutation.mutate(deletingResource.id)
  }

  const submitting = saveMutation.isPending || deleteMutation.isPending

  const renderActions = (resource: FlatResource) => (
    <Group gap={4} justify="flex-end">
      <Tooltip label={t('skills.title')} withArrow>
        <ActionIcon
          variant="subtle"
          color="violet"
          size="sm"
          onClick={() => handleSkill(resource)}
          aria-label={`${resource.name} ${t('skills.title').toLowerCase()}`}
        >
          <IconCertificate size={14} />
        </ActionIcon>
      </Tooltip>
      {/* Week profiles are only meaningful for people: a machine's availability
                is clock windows, not a share of the day. */}
      {resourceType === 'personal' && (
        <Tooltip label={t('workProfiles.short')} withArrow>
          <ActionIcon
            variant="subtle"
            color="teal"
            size="sm"
            onClick={() =>
              setProfileResource({
                id: resource.id,
                name: resource.name,
                group_id: resource.group_id ?? null,
              })
            }
            aria-label={`${resource.name} ${t('workProfiles.short').toLowerCase()}`}
          >
            <IconClockHour4 size={14} />
          </ActionIcon>
        </Tooltip>
      )}
      {/* Operating hours belong to the resource, not to a global calendar page:
                the question "which clock hours does THIS hall run" is only answerable
                here. Personal resources use week profiles instead. */}
      {resourceType === 'infrastructure' && (
        <Tooltip label={t('windows.short')} withArrow>
          <ActionIcon
            variant="subtle"
            color="cyan"
            size="sm"
            onClick={() => setWindowResource(resource)}
            aria-label={`${resource.name} ${t('windows.short').toLowerCase()}`}
          >
            <IconClockHour4 size={14} />
          </ActionIcon>
        </Tooltip>
      )}
      <Tooltip label={t('absences.title')} withArrow>
        <ActionIcon
          variant="subtle"
          color="orange"
          size="sm"
          onClick={() => handleAbsence(resource)}
          aria-label={`${resource.name} ${t('absences.title').toLowerCase()}`}
        >
          <IconCalendarOff size={14} />
        </ActionIcon>
      </Tooltip>
      {canEditGroup(resource.group_id) && (
        <Tooltip label={t('common.edit')} withArrow>
          <ActionIcon
            variant="subtle"
            color="blue"
            size="sm"
            onClick={() => handleEdit(resource)}
            aria-label={`${resource.name} ${t('common.edit').toLowerCase()}`}
          >
            <IconEdit size={14} />
          </ActionIcon>
        </Tooltip>
      )}
      {canEditGroup(resource.group_id) && (
        <Tooltip label={t('common.delete')} withArrow>
          <ActionIcon
            variant="subtle"
            color="red"
            size="sm"
            onClick={() => handleDeleteClick(resource)}
            aria-label={`${resource.name} ${t('common.delete').toLowerCase()}`}
          >
            <IconTrash size={14} />
          </ActionIcon>
        </Tooltip>
      )}
    </Group>
  )

  return (
    <>
      <ResourcesTable
        key={resourceType}
        resources={flatResources}
        loading={loading}
        hasSites={hasSites}
        searchLabel={t(labels.search)}
        emptyLabel={t(labels.empty)}
        createLabel={t(labels.new)}
        canWrite={canWrite}
        onCreate={handleCreate}
        renderActions={renderActions}
        onConflicts={(resource) => navigate(`/planning?resource=${resource.id}`)}
        testId={`${resourceType}-resources-table`}
      />

      <Modal
        opened={formOpened}
        onClose={closeForm}
        title={editingResource ? t(labels.edit) : t(labels.new)}
        size="md"
      >
        <ResourceForm
          key={editingResource?.id ?? 'new'}
          resourceType={resourceType}
          initialValues={editingResource}
          onSubmit={handleSubmit}
          loading={submitting}
        />
      </Modal>

      <Modal opened={deleteOpened} onClose={closeDelete} title={t(labels.deactivate)} size="sm">
        <Text mb="md">{t(labels.deactivateConfirm, { name: deletingResource?.name ?? '' })}</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={closeDelete}>
            {t('common.cancel')}
          </Button>
          <Button color="red" onClick={handleDelete} loading={submitting}>
            {t('common.deactivate')}
          </Button>
        </Group>
      </Modal>

      <SkillMatrixDrawer
        resourceId={skillResource?.id ?? ''}
        resourceName={skillResource?.name ?? ''}
        resourceType={resourceType}
        opened={skillResource !== null}
        onClose={() => setSkillResource(null)}
      />

      <WorkProfileDrawer
        resourceId={profileResource?.id ?? ''}
        resourceName={profileResource?.name ?? ''}
        groupId={profileResource?.group_id ?? null}
        opened={profileResource !== null}
        onClose={() => setProfileResource(null)}
      />

      <AvailabilityWindowsDrawer
        resourceId={windowResource?.id ?? ''}
        resourceName={windowResource?.name ?? ''}
        opened={windowResource !== null}
        onClose={() => setWindowResource(null)}
      />

      <AbsenceDrawer
        resourceId={absenceResource?.id ?? ''}
        resourceName={absenceResource?.name ?? ''}
        resourceType={resourceType}
        opened={absenceResource !== null}
        onClose={() => setAbsenceResource(null)}
      />
    </>
  )
}
