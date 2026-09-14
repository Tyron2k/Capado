/**
 * Form component for work packages (create/edit).
 * Requirements are managed directly on the work package via the shared RequirementsEditor.
 * A "Copy from Template" convenience copies template requirements to the work package.
 * Requirements: 5.1–5.5, 11.5
 */

import { useEffect, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Divider, Group, NumberInput, Select, Stack, Text, TextInput } from '@mantine/core'
import { useForm } from '@mantine/form'
import { DateField } from '../../components/DateField'
import { showErrorNotification } from '../../utils/errorHandling'
import type { WorkPackage } from '../../types/workPackage'
import type { WorkPackageRequirement } from '../../types/workPackage'
import {
  getWorkPackageRequirements,
  addWorkPackageRequirement,
  removeWorkPackageRequirement,
} from '../../api/workPackages'
import { getTemplates, type TemplateListItem } from '../../api/templates'
import { RequirementsEditor } from '../../components/RequirementsEditor'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { compareDates, toIsoDate, type DateFormValue } from '../../utils/date'

export interface WorkPackageFormValues {
  name: string
  /** Mantine date inputs emit `YYYY-MM-DD` strings; see {@link DateFormValue}. */
  start_date: DateFormValue
  end_date: DateFormValue
  /**
   * Duration in WORKING days. Empty means no claim, which is different from zero —
   * a zero-day process is a data error, not a shorter one.
   */
  lead_time_working_days: number | ''
  copy_template_id?: string | null
}

interface WorkPackageFormProps {
  workPackage?: WorkPackage | null
  onSubmit: (values: WorkPackageFormValues) => void
  onCancel: () => void
  loading?: boolean
}

/**
 * Work package create/edit form with inline requirements management.
 * Requirements are stored directly on the work package. Templates serve
 * only as a convenience for copying requirements.
 */
export function WorkPackageForm({
  workPackage,
  onSubmit,
  onCancel,
  loading,
}: WorkPackageFormProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [copyTemplateId, setCopyTemplateId] = useState<string | null>(null)

  // Requirements state (only available when editing an existing work package)

  const form = useForm<WorkPackageFormValues>({
    initialValues: {
      name: '',
      start_date: null,
      end_date: null,
      lead_time_working_days: '',
    },
    validate: {
      name: (value) => (value.trim() ? null : t('workPackageForm.validation.nameRequired')),
      start_date: (value) => (value ? null : t('workPackageForm.validation.startDateRequired')),
      end_date: (value, values) => {
        if (!value) return t('workPackageForm.validation.endDateRequired')
        if (values.start_date && compareDates(value, values.start_date) < 0) {
          return t('workPackageForm.validation.endDateAfterStart')
        }
        return null
      },
    },
  })

  /**
   * The template picker's options. Shares `templates.list()` with the templates panel, so editing a
   * template there refreshes this picker rather than leaving it offering the old name.
   *
   * Fails silently, as before: copying from a template is optional, and an empty picker says so.
   */
  const templatesQuery = useQuery({
    queryKey: queryKeys.templates.list(),
    queryFn: () => getTemplates(),
  })
  const templates: TemplateListItem[] = templatesQuery.data ?? []

  useEffect(() => {
    if (workPackage) {
      form.setValues({
        name: workPackage.name,
        start_date: toIsoDate(workPackage.start_date),
        end_date: toIsoDate(workPackage.end_date),
        lead_time_working_days: workPackage.lead_time_working_days ?? '',
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workPackage])

  /**
   * The requirements of the package being edited. `enabled` covers the "creating a new one" case that
   * the old effect handled with an explicit `setRequirements([])` — no package means no query, so there
   * is nothing to clear.
   *
   * Shares `projects.requirements(id)` with ProblemCard's swap-candidate computation, which reads the
   * same list to decide who is qualified. Adding a requirement here therefore invalidates that too.
   */
  const requirementsQuery = useQuery({
    queryKey: queryKeys.projects.requirements(workPackage?.id ?? 'none'),
    queryFn: () => getWorkPackageRequirements(workPackage!.id),
    enabled: Boolean(workPackage),
  })
  const requirements: WorkPackageRequirement[] = requirementsQuery.data ?? []

  /**
   * A REQUIREMENT DECIDES WHETHER AN ASSIGNMENT STILL FITS.
   *
   * It is not project master data: adding "needs a certified welder" to a package can make an existing
   * assignment unqualified, which is a skill conflict and a digest finding. The old version reloaded
   * this list alone, so the mismatch appeared only once something else refetched.
   */
  const invalidateAfterRequirementChange = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
    ])

  const addReqMutation = useMutation({
    mutationFn: (data: { skill_id: string; skill_attribute_id: string | null; quantity: number }) =>
      addWorkPackageRequirement(workPackage!.id, data),
    onSuccess: () => invalidateAfterRequirementChange(),
    onError: (error) => showErrorNotification(error, t('common.error'), t('common.genericError')),
  })

  const removeReqMutation = useMutation({
    mutationFn: (req: WorkPackageRequirement) =>
      removeWorkPackageRequirement(workPackage!.id, req.id),
    onSuccess: () => invalidateAfterRequirementChange(),
    onError: (error) => showErrorNotification(error, t('common.error'), t('common.genericError')),
  })

  const reqLoading = addReqMutation.isPending || removeReqMutation.isPending

  const handleAddRequirement = (data: {
    skill_id: string
    skill_attribute_id: string | null
    quantity: number
  }) => {
    if (!workPackage) return Promise.resolve()
    return addReqMutation.mutateAsync(data).then(() => undefined)
  }

  const handleRemoveRequirement = (req: WorkPackageRequirement) => {
    if (!workPackage) return Promise.resolve()
    return removeReqMutation.mutateAsync(req).then(() => undefined)
  }

  const templateOptions = templates.map((tpl) => ({ value: tpl.id, label: tpl.name }))

  const handleFormSubmit = (values: WorkPackageFormValues) => {
    onSubmit({ ...values, copy_template_id: !workPackage ? copyTemplateId : null })
  }

  return (
    <form onSubmit={form.onSubmit(handleFormSubmit)}>
      <Stack gap="md">
        <TextInput
          label={t('common.name')}
          placeholder={t('workPackageForm.namePlaceholder')}
          required
          {...form.getInputProps('name')}
        />
        <DateField
          label={t('workPackageForm.startDate')}
          placeholder={t('workPackageForm.startDatePlaceholder')}
          required
          {...form.getInputProps('start_date')}
        />
        <NumberInput
          label={t('workPackageForm.leadTime')}
          description={t('workPackageForm.leadTimeDesc')}
          min={1}
          allowDecimal={false}
          allowNegative={false}
          {...form.getInputProps('lead_time_working_days')}
        />
        <DateField
          label={t('workPackageForm.endDate')}
          placeholder={t('workPackageForm.endDatePlaceholder')}
          required
          {...form.getInputProps('end_date')}
        />

        {/* Requirements section */}
        <Divider />
        <Text fw={600} size="sm">
          {t('requirements.title')}
        </Text>

        {!workPackage ? (
          <>
            {/* When creating: offer template selection to pre-fill requirements */}
            <Select
              label={t('workPackages.copyFromTemplate')}
              placeholder={t('workPackageTemplate.selectTemplate')}
              data={templateOptions}
              value={copyTemplateId}
              onChange={setCopyTemplateId}
              searchable
              clearable
              size="sm"
            />
            <Text size="xs" c="dimmed">
              {t('workPackages.saveFirst')}
            </Text>
          </>
        ) : (
          <>
            {/* When editing: manage requirements via shared editor */}
            <RequirementsEditor
              requirements={requirements}
              onAdd={handleAddRequirement}
              onRemove={handleRemoveRequirement}
              loading={reqLoading}
            />
          </>
        )}

        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" loading={loading}>
            {t('common.save')}
          </Button>
        </Group>
      </Stack>
    </form>
  )
}
