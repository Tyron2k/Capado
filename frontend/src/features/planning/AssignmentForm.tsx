/**
 * Form component for assignments (create/edit).
 *
 * Two input shapes depending on resource type:
 *   Personal → start date, end date, hours/day.
 *   Infrastructure → start time, end time (minute-precision timestamps).
 *
 * Requirements: 5.1, 5.4, 5.5, 5.6, 5.8, 6.1–6.5, 7.1, 7.3, 7.4, 10.1, 10.4
 */

import { useEffect, useMemo, useState } from 'react'

import { useMutation, useQuery } from '@tanstack/react-query'
import { Button, Group, NumberInput, SegmentedControl, Select, Stack } from '@mantine/core'
import { useForm } from '@mantine/form'
import { DateField, DateTimeField } from '../../components/DateField'
import type { WorkPackage } from '../../types/workPackage'
import type { Project } from '../../types/project'
import type { Assignment, AssignmentPreview, ResourceType } from '../../types/assignment'
import { previewAssignment } from '../../api/assignments'
import { getProjects } from '../../api/projects'
import { getWorkPackages } from '../../api/workPackages'
import { AutocompleteField } from '../../components/AutocompleteField'
import { SuggestionList } from './SuggestionList'
import { AssignmentPreviewSummary } from './AssignmentPreviewSummary'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { showErrorNotification } from '../../utils/errorHandling'
import { toAssignmentPayload } from './assignmentUtils'
import {
  compareDateTimes,
  compareDates,
  toIsoDate,
  toIsoDateTime,
  type DateFormValue,
} from '../../utils/date'

export interface AssignmentFormValues {
  resource_id: string
  resource_type: ResourceType
  work_package_id: string
  // Personal fields — Mantine date inputs emit `YYYY-MM-DD` strings.
  start_date: DateFormValue
  end_date: DateFormValue
  allocation_percent: number
  // Infrastructure fields — `DateTimePicker` emits `YYYY-MM-DD HH:mm:ss` strings.
  start_at: DateFormValue
  end_at: DateFormValue
}

interface AssignmentFormProps {
  assignment?: Assignment | null
  onSubmit: (values: AssignmentFormValues) => void
  onCancel: () => void
  loading?: boolean
}

export function AssignmentForm({ assignment, onSubmit, onCancel, loading }: AssignmentFormProps) {
  const { t } = useTranslation()
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const [resourceType, setResourceType] = useState<ResourceType>('personal')
  const [preview, setPreview] = useState<{ signature: string; result: AssignmentPreview } | null>(
    null,
  )

  const form = useForm<AssignmentFormValues>({
    initialValues: {
      resource_id: '',
      resource_type: 'personal',
      work_package_id: '',
      start_date: null,
      end_date: null,
      allocation_percent: 100,
      start_at: null,
      end_at: null,
    },
    validate: {
      resource_id: (value) => (value ? null : t('assignmentForm.validation.resourceRequired')),
      work_package_id: (value) =>
        value ? null : t('assignmentForm.validation.workPackageRequired'),
      start_date: (value, values) => {
        if (values.resource_type !== 'personal') return null
        if (!value) return t('assignmentForm.validation.startDateRequired')
        return null
      },
      end_date: (value, values) => {
        if (values.resource_type !== 'personal') return null
        if (!value) return t('assignmentForm.validation.endDateRequired')
        if (values.start_date && compareDates(value, values.start_date) < 0) {
          return t('assignmentForm.validation.endDateAfterStart')
        }
        return null
      },
      allocation_percent: (value, values) => {
        if (values.resource_type !== 'personal') return null
        if (!value || value <= 0) return t('assignmentForm.validation.allocationMin')
        if (value > 100) return t('assignmentForm.validation.allocationMax')
        return null
      },
      start_at: (value, values) => {
        if (values.resource_type !== 'infrastructure') return null
        if (!value) return t('assignmentForm.validation.startTimeRequired')
        return null
      },
      end_at: (value, values) => {
        if (values.resource_type !== 'infrastructure') return null
        if (!value) return t('assignmentForm.validation.endTimeRequired')
        if (values.start_at && compareDateTimes(value, values.start_at) <= 0) {
          return t('assignmentForm.validation.endTimeAfterStart')
        }
        return null
      },
    },
  })

  /**
   * A DEPENDENT PAIR: the work packages depend on the selected project.
   *
   * The hand-written version had two effects, two AbortControllers and a `loadingWorkPackages` flag,
   * plus a `setWorkPackages([])` in the no-project branch to clear the previous project's packages.
   * `enabled` does the clearing by construction — with no project there is no query, so there is
   * nothing stale to show — and the project id in the key means switching projects cannot land the old
   * project's packages under the new one's name.
   *
   * Both swallow their errors, and that is kept: this is a form, and the empty select already says the
   * list is unavailable. A notification here would fire behind a modal the user is still filling in.
   */
  const projectsQuery = useQuery({
    queryKey: queryKeys.projects.list(),
    queryFn: () => getProjects(),
  })
  const projects: Project[] = projectsQuery.data ?? []

  const workPackagesQuery = useQuery({
    queryKey: queryKeys.projects.workPackages(selectedProjectId ?? 'none'),
    queryFn: () => getWorkPackages(selectedProjectId as string),
    enabled: Boolean(selectedProjectId),
  })
  const workPackages: WorkPackage[] = workPackagesQuery.data ?? []
  const loadingWorkPackages = Boolean(selectedProjectId) && workPackagesQuery.isPending

  useEffect(() => {
    if (assignment) {
      form.setValues({
        resource_id: assignment.resource_id,
        resource_type: assignment.resource_type,
        work_package_id: assignment.work_package_id,
        start_date: assignment.start_date ? toIsoDate(assignment.start_date) : null,
        end_date: assignment.end_date ? toIsoDate(assignment.end_date) : null,
        allocation_percent: assignment.allocation_percent ?? 100,
        start_at: assignment.start_at ? toIsoDateTime(assignment.start_at) : null,
        end_at: assignment.end_at ? toIsoDateTime(assignment.end_at) : null,
      })
      setResourceType(assignment.resource_type)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assignment])

  useEffect(() => {
    if (assignment && projects.length > 0 && !selectedProjectId) {
      // Use project_id directly from the assignment instead of scanning all projects
      if (assignment.project_id) {
        setSelectedProjectId(assignment.project_id)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assignment, projects])

  const handleResourceAutocompleteChange = (id: string | null, _name: string) => {
    form.setFieldValue('resource_id', id || '')
    form.setFieldValue('resource_type', resourceType)
  }

  const handleResourceTypeChange = (value: string) => {
    const newType = value as ResourceType
    setResourceType(newType)
    form.setFieldValue('resource_id', '')
    form.setFieldValue('resource_type', newType)
    // Clear fields belonging to the other shape to keep validation clean.
    if (newType === 'personal') {
      form.setFieldValue('start_at', null)
      form.setFieldValue('end_at', null)
    } else {
      form.setFieldValue('start_date', null)
      form.setFieldValue('end_date', null)
    }
  }

  const handleProjectChange = (value: string | null) => {
    setSelectedProjectId(value)
    form.setFieldValue('work_package_id', '')
  }

  const handleSuggestionSelect = (resourceId: string, suggestionResourceType: ResourceType) => {
    form.setFieldValue('resource_id', resourceId)
    form.setFieldValue('resource_type', suggestionResourceType)
    setResourceType(suggestionResourceType)
  }

  const projectSelectData = useMemo(
    () => projects.map((p) => ({ value: p.id, label: p.name })),
    [projects],
  )

  const workPackageSelectData = useMemo(
    () => workPackages.map((wp) => ({ value: wp.id, label: wp.name })),
    [workPackages],
  )

  const isPersonal = resourceType === 'personal'

  const isEditing = !!assignment
  const currentSignature = JSON.stringify(form.values)
  const visiblePreview = preview?.signature === currentSignature ? preview.result : null
  const previewMutation = useMutation({
    mutationFn: (values: AssignmentFormValues) =>
      previewAssignment({ ...toAssignmentPayload(values), assignment_id: assignment?.id }),
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('common.unexpectedError')),
  })

  const handlePreview = () => {
    if (form.validate().hasErrors) return
    const values = { ...form.values }
    const signature = JSON.stringify(values)
    setPreview(null)
    previewMutation.mutate(values, {
      onSuccess: (result) => setPreview({ signature, result }),
    })
  }

  return (
    <form onSubmit={form.onSubmit(onSubmit)}>
      <Stack gap="md">
        {!isEditing && (
          <SegmentedControl
            value={resourceType}
            onChange={handleResourceTypeChange}
            data={[
              { label: t('assignmentForm.personal'), value: 'personal' },
              { label: t('assignmentForm.infrastructure'), value: 'infrastructure' },
            ]}
            fullWidth
          />
        )}

        <AutocompleteField
          type={resourceType}
          label={t('assignmentForm.resource')}
          placeholder={
            isPersonal ? t('assignmentForm.searchPersonal') : t('assignmentForm.searchInfra')
          }
          value={form.values.resource_id || null}
          onChange={handleResourceAutocompleteChange}
          required
          error={form.errors.resource_id as string | undefined}
        />

        <Select
          label={t('assignmentForm.project')}
          placeholder={t('assignmentForm.projectPlaceholder')}
          searchable
          data={projectSelectData}
          value={selectedProjectId}
          onChange={handleProjectChange}
        />

        <Select
          label={t('assignmentForm.workPackage')}
          placeholder={
            selectedProjectId
              ? t('assignmentForm.workPackagePlaceholder')
              : t('assignmentForm.workPackageDisabled')
          }
          required
          searchable
          data={workPackageSelectData}
          value={form.values.work_package_id || null}
          onChange={(value) => form.setFieldValue('work_package_id', value || '')}
          error={form.errors.work_package_id}
          disabled={!selectedProjectId || loadingWorkPackages}
        />

        {isPersonal ? (
          <>
            <DateField
              label={t('assignmentForm.startDate')}
              placeholder={t('assignmentForm.startDatePlaceholder')}
              required
              {...form.getInputProps('start_date')}
            />
            <DateField
              label={t('assignmentForm.endDate')}
              placeholder={t('assignmentForm.endDatePlaceholder')}
              required
              {...form.getInputProps('end_date')}
            />
            <NumberInput
              label={t('assignmentForm.allocation')}
              placeholder={t('assignmentForm.allocationPlaceholder')}
              required
              min={5}
              max={100}
              step={5}
              decimalScale={0}
              suffix="%"
              {...form.getInputProps('allocation_percent')}
            />
          </>
        ) : (
          <>
            <DateTimeField
              label={t('assignmentForm.occupiedFrom')}
              placeholder={t('assignmentForm.occupiedFromPlaceholder')}
              required
              {...form.getInputProps('start_at')}
            />
            <DateTimeField
              label={t('assignmentForm.occupiedUntil')}
              placeholder={t('assignmentForm.occupiedUntilPlaceholder')}
              required
              {...form.getInputProps('end_at')}
            />
          </>
        )}

        {visiblePreview && <AssignmentPreviewSummary preview={visiblePreview} />}

        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button
            type="button"
            variant="light"
            onClick={handlePreview}
            loading={previewMutation.isPending}
          >
            {t('assignmentForm.preview')}
          </Button>
          <Button type="submit" loading={loading}>
            {t('common.save')}
          </Button>
        </Group>
      </Stack>

      {isPersonal && !isEditing && (
        <SuggestionList
          skillId={null}
          skillAttributeId={null}
          startDate={form.values.start_date}
          endDate={form.values.end_date}
          allocationPercent={form.values.allocation_percent}
          onSelect={handleSuggestionSelect}
        />
      )}
    </form>
  )
}
