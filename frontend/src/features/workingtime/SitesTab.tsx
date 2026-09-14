/**
 * Sites tab: the top organisational level, and the owner of the holiday calendar.
 *
 * A site is not cosmetic. Public holidays differ per location, so which site a
 * resource belongs to changes what its capacity actually is.
 */

import { useEffect, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Modal,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconEdit, IconPlus, IconTrash } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { DataTable } from '../../components/layout'
import { showErrorNotification } from '../../utils/errorHandling'
import {
  createSite,
  deactivateSite,
  listSites,
  updateSite,
  type Site,
  type SiteInput,
} from '../../api/calendar'

export function SitesTab() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<Site | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [form, setForm] = useState<SiteInput>({ name: '', region_code: '', is_default: false })

  const sitesQuery = useQuery({
    queryKey: queryKeys.sites.list(),
    queryFn: () => listSites(),
  })
  const sites: Site[] = sitesQuery.data ?? []
  const loading = sitesQuery.isPending

  useEffect(() => {
    if (sitesQuery.error) {
      showErrorNotification(sitesQuery.error, t('common.error'), t('workingTime.sites.loadError'))
    }
  }, [sitesQuery.error, t])

  /**
   * SECOND SCREEN, AND THE FIRST MUTATION — which is where the key convention gets its real test.
   *
   * The reads were the easy half. A mutation has to say what it made untrue, and that is not always
   * its own list: renaming a site changes what every RESOURCE list displays, because `site_name` is
   * denormalised onto those responses. The old code called `await load()` and refreshed this table
   * only, so a rename left the people and infrastructure tables showing the previous name until
   * something else happened to refetch them. Nobody would have called that a bug; they would have
   * called the application unreliable.
   *
   * Both invalidations are therefore listed together, at the point where the reason is known. The
   * resources one is currently a no-op because those screens are not converted — see the note on
   * `queryKeys.resources.all` for why it is written now rather than left to be remembered later.
   */
  const invalidateAfterSiteChange = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.sites.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.all }),
    ])
  }

  const saveMutation = useMutation({
    mutationFn: (payload: SiteInput) =>
      editing ? updateSite(editing.id, payload) : createSite(payload),
    onSuccess: async () => {
      notifications.show({ message: t('workingTime.sites.saved'), color: 'green' })
      setModalOpen(false)
      await invalidateAfterSiteChange()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('workingTime.sites.saveError')),
  })

  const deactivateMutation = useMutation({
    mutationFn: (site: Site) => deactivateSite(site.id),
    onSuccess: async () => {
      notifications.show({ message: t('workingTime.sites.deactivated'), color: 'green' })
      await invalidateAfterSiteChange()
    },
    onError: (error) =>
      showErrorNotification(error, t('common.error'), t('workingTime.sites.deactivateError')),
  })

  const saving = saveMutation.isPending

  const openCreate = () => {
    setEditing(null)
    setForm({ name: '', region_code: '', is_default: false })
    setModalOpen(true)
  }

  const openEdit = (site: Site) => {
    setEditing(site)
    setForm({
      name: site.name,
      region_code: site.region_code ?? '',
      is_default: site.is_default,
    })
    setModalOpen(true)
  }

  const save = () => {
    if (form.name.trim() === '') return
    saveMutation.mutate({
      name: form.name.trim(),
      region_code: form.region_code?.trim() === '' ? null : form.region_code,
      is_default: form.is_default,
    })
  }

  const deactivate = (site: Site) => {
    deactivateMutation.mutate(site)
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Text c="dimmed" size="sm">
          {t('workingTime.sites.hint')}
        </Text>
        <Button leftSection={<IconPlus size={16} />} onClick={openCreate}>
          {t('workingTime.sites.add')}
        </Button>
      </Group>

      <DataTable
        loading={loading}
        empty={sites.length === 0}
        emptyMessage={t('workingTime.sites.empty')}
        testId="sites-table"
        head={
          <Table.Tr>
            <Table.Th>{t('workingTime.sites.name')}</Table.Th>
            <Table.Th>{t('workingTime.sites.regionCode')}</Table.Th>
            <Table.Th>{t('workingTime.sites.isDefault')}</Table.Th>
            <Table.Th />
          </Table.Tr>
        }
      >
        {sites.map((site) => (
          <Table.Tr key={site.id}>
            <Table.Td>{site.name}</Table.Td>
            <Table.Td>{site.region_code ?? '—'}</Table.Td>
            <Table.Td>
              {site.is_default && <Badge color="blue">{t('workingTime.sites.default')}</Badge>}
            </Table.Td>
            <Table.Td>
              <Group gap="xs" justify="flex-end">
                <ActionIcon
                  variant="subtle"
                  data-testid={`site-edit-${site.id}`}
                  onClick={() => openEdit(site)}
                  aria-label={t('common.edit')}
                >
                  <IconEdit size={16} />
                </ActionIcon>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  disabled={site.is_default}
                  data-testid={`site-deactivate-${site.id}`}
                  onClick={() => deactivate(site)}
                  aria-label={t('common.delete')}
                >
                  <IconTrash size={16} />
                </ActionIcon>
              </Group>
            </Table.Td>
          </Table.Tr>
        ))}
      </DataTable>

      <Modal
        opened={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editing ? t('workingTime.sites.edit') : t('workingTime.sites.add')}
      >
        <Stack gap="sm">
          <TextInput
            required
            label={t('workingTime.sites.name')}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.currentTarget.value })}
          />
          <TextInput
            label={t('workingTime.sites.regionCode')}
            description={t('workingTime.sites.regionCodeDesc')}
            placeholder="DE-BY"
            value={form.region_code ?? ''}
            onChange={(e) => setForm({ ...form, region_code: e.currentTarget.value })}
          />
          <Switch
            label={t('workingTime.sites.isDefault')}
            description={t('workingTime.sites.isDefaultDesc')}
            checked={form.is_default ?? false}
            onChange={(e) => setForm({ ...form, is_default: e.currentTarget.checked })}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setModalOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button loading={saving} onClick={save}>
              {t('common.save')}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  )
}
