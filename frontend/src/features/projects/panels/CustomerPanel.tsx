/**
 * Customer administration.
 *
 * Small on purpose: a name, a customer number and a note. Everything else about a customer lives in
 * whatever system actually manages customers, and an address book here would be a second place to
 * keep the same data current.
 *
 * Two things this screen is careful about, because both are ways to lose information:
 *
 * Retiring is offered next to deleting and explained. Deleting clears the link on every folder and
 * project that pointed at the customer; retiring keeps it and only removes them from pickers. An
 * operator who wants "stop offering this one" almost always means retire.
 *
 * A duplicate name comes back as a 409, and the message says the name is taken rather than that the
 * save failed. That distinction is the whole point of the entity: the right response is to pick the
 * existing customer, not to invent a variant spelling.
 */

import { useEffect, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Modal,
  Stack,
  Switch,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconInfoCircle, IconPencil, IconPlus, IconTrash } from '@tabler/icons-react'
import {
  createCustomer,
  deleteCustomer,
  getCustomers,
  updateCustomer,
  type Customer,
} from '../../../api/customers'
import { showErrorNotification } from '../../../utils/errorHandling'
import { useTranslation } from '../../../i18n'
import { queryKeys } from '../../../api/queryClient'

interface DraftState {
  id: string | null
  name: string
  reference: string
  note: string
}

const EMPTY_DRAFT: DraftState = { id: null, name: '', reference: '', note: '' }

export function CustomerPanel() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [showInactive, setShowInactive] = useState(false)
  const [draft, setDraft] = useState<DraftState | null>(null)

  const customersQuery = useQuery({
    queryKey: queryKeys.customers.list(showInactive),
    queryFn: () => getCustomers(showInactive),
  })
  const customers: Customer[] | null = customersQuery.data ?? null

  useEffect(() => {
    if (customersQuery.error) {
      showErrorNotification(customersQuery.error, t('common.error'), t('customers.loadFailed'))
    }
  }, [customersQuery.error, t])

  /**
   * A CUSTOMER'S NAME IS DISPLAYED WHERE IT IS NOT EDITED.
   *
   * Project lists and the folder tree show it, and both customer pickers offer it. The hand-written
   * version reloaded this table alone, so renaming a customer here left every project row showing the
   * old name until something else happened to refetch.
   *
   * Invalidating the coarse `customers.all` covers both list variants — the picker's active-only and
   * this panel's include-inactive — and `projects.all` covers the rows that display the name. No
   * digest: a customer is not a finding, and its name changes nothing about the plan.
   */
  const invalidateAfterCustomerWrite = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.customers.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.all }),
    ])

  const saveMutation = useMutation({
    mutationFn: (d: DraftState) => {
      const payload = { name: d.name.trim(), reference: d.reference.trim(), note: d.note }
      return d.id ? updateCustomer(d.id, payload) : createCustomer(payload)
    },
    onSuccess: async () => {
      setDraft(null)
      await invalidateAfterCustomerWrite()
    },
    onError: (error: unknown) => {
      // A 409 is not a failure to save, it is "that name is taken" — and the right response is
      // to pick the existing customer rather than to retry with a variant spelling.
      const status = (error as { response?: { status?: number } })?.response?.status
      if (status === 409) {
        notifications.show({
          title: t('customers.duplicate'),
          message: t('customers.empty'),
          color: 'orange',
        })
      } else {
        showErrorNotification(error, t('common.error'), t('customers.saveFailed'))
      }
    },
  })

  const saving = saveMutation.isPending

  const save = () => {
    if (!draft || !draft.name.trim()) return
    saveMutation.mutate(draft)
  }

  const removeMutation = useMutation({
    mutationFn: (id: string) => deleteCustomer(id),
    onSuccess: () => invalidateAfterCustomerWrite(),
    onError: (error) => showErrorNotification(error, t('common.error'), t('customers.saveFailed')),
  })

  const remove = (customer: Customer) => {
    const confirmed = window.confirm(
      t('customers.deleteConfirm', {
        name: customer.name,
        folders: customer.folder_count,
        projects: customer.project_count,
      }),
    )
    if (!confirmed) return
    removeMutation.mutate(customer.id)
  }

  const retireMutation = useMutation({
    mutationFn: (customer: Customer) =>
      updateCustomer(customer.id, { is_active: !customer.is_active }),
    onSuccess: () => invalidateAfterCustomerWrite(),
    onError: (error) => showErrorNotification(error, t('common.error'), t('customers.saveFailed')),
  })

  const retire = (customer: Customer) => {
    retireMutation.mutate(customer)
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="wrap">
        <Title order={4}>{t('customers.title')}</Title>
        <Group gap="sm">
          <Switch
            label={t('customers.showInactive')}
            checked={showInactive}
            onChange={(event) => setShowInactive(event.currentTarget.checked)}
            size="sm"
          />
          <Button
            leftSection={<IconPlus size={16} />}
            size="xs"
            data-testid="customer-new"
            onClick={() => setDraft({ ...EMPTY_DRAFT })}
          >
            {t('customers.add')}
          </Button>
        </Group>
      </Group>

      <Alert icon={<IconInfoCircle size={16} />} color="blue" variant="light">
        {t('customers.retireHint')}
      </Alert>

      {customers !== null && customers.length === 0 ? (
        <Alert icon={<IconInfoCircle size={16} />} color="gray" variant="light">
          {t('customers.empty')}
        </Alert>
      ) : (
        <Table striped withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('customers.name')}</Table.Th>
              <Table.Th>{t('customers.reference')}</Table.Th>
              <Table.Th style={{ width: 90 }}>{t('customers.folders')}</Table.Th>
              <Table.Th style={{ width: 90 }}>{t('customers.projects')}</Table.Th>
              <Table.Th style={{ width: 110 }} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(customers ?? []).map((customer) => (
              <Table.Tr key={customer.id}>
                <Table.Td>
                  <Group gap="xs" wrap="nowrap">
                    <Text size="sm">{customer.name}</Text>
                    {!customer.is_active && (
                      <Badge size="sm" color="gray" variant="light">
                        {t('customers.inactive')}
                      </Badge>
                    )}
                  </Group>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">
                    {customer.reference || '–'}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{customer.folder_count}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{customer.project_count}</Text>
                </Table.Td>
                <Table.Td>
                  <Group gap={4} wrap="nowrap">
                    <ActionIcon
                      variant="subtle"
                      aria-label={t('customers.edit')}
                      onClick={() =>
                        setDraft({
                          id: customer.id,
                          name: customer.name,
                          reference: customer.reference,
                          note: customer.note,
                        })
                      }
                    >
                      <IconPencil size={16} />
                    </ActionIcon>
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      data-testid={`customer-retire-${customer.id}`}
                      onClick={() => void retire(customer)}
                    >
                      {customer.is_active ? t('customers.inactive') : t('customers.active')}
                    </Button>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      aria-label={t('common.delete')}
                      data-testid={`customer-delete-${customer.id}`}
                      onClick={() => void remove(customer)}
                    >
                      <IconTrash size={16} />
                    </ActionIcon>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Modal
        opened={draft !== null}
        onClose={() => setDraft(null)}
        title={draft?.id ? t('customers.edit') : t('customers.add')}
      >
        {draft && (
          <Stack gap="sm">
            <TextInput
              label={t('customers.name')}
              data-testid="customer-draft-name"
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.currentTarget.value })}
              maxLength={255}
              required
            />
            <TextInput
              label={t('customers.reference')}
              value={draft.reference}
              onChange={(event) => setDraft({ ...draft, reference: event.currentTarget.value })}
              maxLength={128}
            />
            <Textarea
              label={t('customers.note')}
              value={draft.note}
              onChange={(event) => setDraft({ ...draft, note: event.currentTarget.value })}
              maxLength={1000}
              autosize
              minRows={2}
            />
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setDraft(null)}>
                {t('common.cancel')}
              </Button>
              <Button
                loading={saving}
                disabled={!draft.name.trim()}
                data-testid="customer-draft-save"
                onClick={() => void save()}
              >
                {t('common.save')}
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Stack>
  )
}
