/**
 * Form component for projects (create/edit).
 * Requirements: 4.1–4.5, 11.5
 */

import { useEffect } from 'react'
import { Button, Group, NumberInput, Select, TextInput, Stack } from '@mantine/core'
import { useForm } from '@mantine/form'
import { DateField } from '../../components/DateField'
import { useCustomerOptions } from './useCustomerOptions'
import type { Project, ProjectFolder, ProjectPriority } from '../../types/project'
import { useTranslation } from '../../i18n'
import { compareDates, toIsoDate, type DateFormValue } from '../../utils/date'

export interface ProjectFormValues {
  name: string
  /** Mantine date inputs emit `YYYY-MM-DD` strings; see {@link DateFormValue}. */
  start_date: DateFormValue
  end_date: DateFormValue
  /** Optional grouping. null means unfiled, which is the normal default. */
  folder_id: string | null
  /** Order within the folder. */
  position: number
  /** Identifier from the customer's own system; empty is stored as null. */
  external_ref: string
  /** What was promised. Empty means nothing was, which is not the same as on time. */
  committed_delivery_date: DateFormValue
  /** Who the work is for; empty is stored as null and means internal work. */
  customer_id: string | null
  priority: ProjectPriority
}

interface ProjectFormProps {
  project?: Project | null
  /** Folders offered in the picker. Empty is fine — grouping is optional. */
  folders?: ProjectFolder[]
  /** Preselected folder when creating from inside one. */
  defaultFolderId?: string | null
  onSubmit: (values: ProjectFormValues) => void
  onCancel: () => void
  loading?: boolean
}

export function ProjectForm({
  project,
  folders = [],
  defaultFolderId = null,
  onSubmit,
  onCancel,
  loading,
}: ProjectFormProps) {
  const customerOptions = useCustomerOptions()
  // The inherited name comes from the project the form was opened on; for a new project the
  // folder is not yet chosen, so there is nothing to inherit from and the field simply reads
  // "no customer".
  const inheritedCustomerName = project?.customer_inherited ? project.customer_name : null
  const { t } = useTranslation()
  const form = useForm<ProjectFormValues>({
    initialValues: {
      name: '',
      start_date: null,
      end_date: null,
      folder_id: defaultFolderId,
      position: 0,
      external_ref: '',
      committed_delivery_date: null,
      customer_id: null,
      priority: 'normal',
    },
    validate: {
      name: (value) => (value.trim() ? null : t('projectForm.validation.nameRequired')),
      start_date: (value) => (value ? null : t('projectForm.validation.startDateRequired')),
      end_date: (value, values) => {
        if (!value) return t('projectForm.validation.endDateRequired')
        if (values.start_date && compareDates(value, values.start_date) < 0) {
          return t('projectForm.validation.endDateAfterStart')
        }
        return null
      },
    },
  })

  useEffect(() => {
    if (project) {
      form.setValues({
        name: project.name,
        start_date: toIsoDate(project.start_date),
        end_date: toIsoDate(project.end_date),
        folder_id: project.folder_id,
        position: project.position,
        // null and '' are the same thing to the user; the panel maps '' back to null.
        external_ref: project.external_ref ?? '',
        committed_delivery_date: project.committed_delivery_date
          ? toIsoDate(project.committed_delivery_date)
          : null,
        customer_id: project.customer_id ?? null,
        priority: project.priority,
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project])

  return (
    <form onSubmit={form.onSubmit(onSubmit)}>
      <Stack gap="md">
        <TextInput
          label={t('common.name')}
          placeholder={t('projectForm.namePlaceholder')}
          required
          {...form.getInputProps('name')}
        />
        <DateField
          label={t('projectForm.startDate')}
          placeholder={t('projectForm.startDatePlaceholder')}
          required
          {...form.getInputProps('start_date')}
        />
        <DateField
          label={t('projectForm.endDate')}
          placeholder={t('projectForm.endDatePlaceholder')}
          required
          {...form.getInputProps('end_date')}
        />
        <Select
          label={t('projectForm.customer')}
          // Says where the value comes from when it is inherited, so an operator does not pick
          // the same customer explicitly and pin it to the project for no reason.
          description={
            inheritedCustomerName
              ? t('projectForm.customerInherited', { name: inheritedCustomerName })
              : t('projectForm.customerDesc')
          }
          placeholder={
            inheritedCustomerName
              ? t('projectForm.customerFromFolder')
              : t('projectForm.customerNone')
          }
          data={customerOptions}
          clearable
          searchable
          value={form.values.customer_id}
          onChange={(value) => form.setFieldValue('customer_id', value)}
        />
        <Select
          label={t('projectForm.priority')}
          description={t('projectForm.priorityDesc')}
          allowDeselect={false}
          data={[
            { value: 'low', label: t('projectForm.priorityLow') },
            { value: 'normal', label: t('projectForm.priorityNormal') },
            { value: 'high', label: t('projectForm.priorityHigh') },
            { value: 'critical', label: t('projectForm.priorityCritical') },
          ]}
          {...form.getInputProps('priority')}
        />
        <DateField
          label={t('projectForm.committedDelivery')}
          description={t('projectForm.committedDeliveryDesc')}
          clearable
          {...form.getInputProps('committed_delivery_date')}
        />
        <TextInput
          label={t('projectForm.externalRef')}
          description={t('projectForm.externalRefDesc')}
          placeholder={t('projectForm.externalRefPlaceholder')}
          maxLength={128}
          {...form.getInputProps('external_ref')}
        />
        <Select
          label={t('projectForm.folder')}
          description={t('projectForm.folderDesc')}
          placeholder={t('projectForm.noFolder')}
          clearable
          data={folders.map((f) => ({ value: f.id, label: f.name }))}
          {...form.getInputProps('folder_id')}
        />
        <NumberInput
          label={t('projectForm.position')}
          description={t('projectForm.positionDesc')}
          min={0}
          allowDecimal={false}
          allowNegative={false}
          {...form.getInputProps('position')}
        />
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
