/**
 * Unified form for creating/editing personal and infrastructure resources.
 * Loads groups filtered by resource type and provides a searchable dropdown.
 *
 * THE SITE FIELD IS CLEARABLE, AND THAT IS LOAD-BEARING. An empty selection means "at no site",
 * which is a legitimate state — a single-plant operator files nothing at one — and it must be
 * distinguishable from "do not change the site". Mantine's Select yields '' when cleared, so the
 * submit handler maps '' to null and the caller sends null to REMOVE the site. Sending undefined
 * instead would leave a stale site in place with no way to get rid of it.
 *
 * The site list is loaded once and hidden entirely when the installation has none, so a
 * single-plant operator never sees a control that can only be empty.
 */

import { useMemo } from 'react'

import { useQuery } from '@tanstack/react-query'
import { Button, Group, Select, TextInput } from '@mantine/core'
import { useForm } from '@mantine/form'
import { getGroups } from '../../api/resources'
import { listSites } from '../../api/calendar'
import { normalizeSiteId } from './utils/siteValue'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'

interface ResourceFormValues {
  name: string
  group_id: string
  /** null means "at no site". Never undefined — see the note at the top of this file. */
  site_id: string | null
}

interface ResourceFormProps {
  /** Determines which groups are shown in the dropdown. */
  resourceType: 'personal' | 'infrastructure'
  /** Pre-fill form for editing. */
  initialValues?: { name: string; group_id: string; site_id?: string | null } | null
  /** Called with validated form values on submit. */
  onSubmit: (values: ResourceFormValues) => void | Promise<void>
  /** Shows a loading spinner on the submit button. */
  loading?: boolean
}

export function ResourceForm({
  resourceType,
  initialValues,
  onSubmit,
  loading = false,
}: ResourceFormProps) {
  const { t } = useTranslation()
  /**
   * BOTH PICKERS NOW SHARE THEIR DATA WITH THE SCREENS THAT EDIT IT.
   *
   * `resources.groups(type)` belongs to GroupsPanel and `sites.list()` to SitesTab, both converted
   * earlier. Those screens already invalidated these keys when nothing read them yet — a deliberate
   * no-op written so that nobody would have to REMEMBER to come back and add it here. This is the
   * turn where the no-op starts paying: renaming a site now updates this form's picker, and the
   * mutation that does it was written weeks of migration ago and never touched again.
   *
   * Both still degrade to an empty picker on failure. A resource with no group cannot be saved
   * anyway, and the form's own validation says so more usefully than a notification would.
   */
  const groupsQuery = useQuery({
    queryKey: queryKeys.resources.groups(resourceType),
    queryFn: () => getGroups(resourceType),
  })
  const groupOptions = useMemo(
    () => (groupsQuery.data ?? []).map((g) => ({ value: g.id, label: g.name })),
    [groupsQuery.data],
  )

  const sitesQuery = useQuery({
    queryKey: queryKeys.sites.list(),
    queryFn: () => listSites(),
  })
  const siteOptions = useMemo(
    () => (sitesQuery.data ?? []).map((s) => ({ value: s.id, label: s.name })),
    [sitesQuery.data],
  )

  const form = useForm<ResourceFormValues>({
    initialValues: {
      name: initialValues?.name ?? '',
      group_id: initialValues?.group_id ?? '',
      site_id: initialValues?.site_id ?? null,
    },
    validate: {
      name: (value) => (!value.trim() ? t('resources.form.nameRequired') : null),
      group_id: (value) => (!value ? t('resources.form.groupRequired') : null),
    },
  })

  return (
    <form
      onSubmit={form.onSubmit((values) =>
        onSubmit({ ...values, site_id: normalizeSiteId(values.site_id) }),
      )}
    >
      <TextInput
        label={t('common.name')}
        placeholder={t('resources.form.namePlaceholder')}
        required
        mb="md"
        {...form.getInputProps('name')}
      />

      <Select
        label={t('resources.group')}
        placeholder={t('resources.form.groupPlaceholder')}
        data={groupOptions}
        searchable
        required
        mb="md"
        {...form.getInputProps('group_id')}
      />

      {siteOptions.length > 0 && (
        <Select
          label={t('resources.site')}
          description={t('resources.form.siteHint')}
          placeholder={t('resources.form.sitePlaceholder')}
          data={siteOptions}
          searchable
          clearable
          mb="md"
          {...form.getInputProps('site_id')}
        />
      )}

      <Group justify="flex-end">
        <Button type="submit" loading={loading}>
          {initialValues ? t('common.save') : t('common.create')}
        </Button>
      </Group>
    </form>
  )
}
