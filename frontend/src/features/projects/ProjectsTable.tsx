/** Project table pilot: stateful table behaviour, with the existing Mantine presentation. */
import { useEffect, useMemo, useState } from 'react'
import type { RowSelectionState } from '@tanstack/react-table'
import {
  columnFilteringFeature,
  columnVisibilityFeature,
  createColumnHelper,
  createFilteredRowModel,
  createSortedRowModel,
  filterFn_equalsString,
  filterFn_includesString,
  flexRender,
  globalFilteringFeature,
  rowSelectionFeature,
  rowSortingFeature,
  sortFn_basic,
  sortFn_text,
  tableFeatures,
  useTable,
} from '@tanstack/react-table'
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Checkbox,
  Group,
  Menu,
  Select,
  Table,
  Text,
  TextInput,
  UnstyledButton,
} from '@mantine/core'
import {
  IconArrowDown,
  IconArrowUp,
  IconColumns,
  IconEdit,
  IconPackage,
  IconPlus,
  IconSearch,
  IconTrash,
} from '@tabler/icons-react'
import { DataTable, FilterBar } from '../../components/layout'
import { useTranslation } from '../../i18n'
import type { Project, ProjectPriority } from '../../types/project'
import { formatDate } from '../../utils/date'

const features = tableFeatures({
  columnFilteringFeature,
  columnVisibilityFeature,
  globalFilteringFeature,
  rowSelectionFeature,
  rowSortingFeature,
  filteredRowModel: createFilteredRowModel(),
  sortedRowModel: createSortedRowModel(),
  filterFns: { equals: filterFn_equalsString, includes: filterFn_includesString },
  sortFns: { basic: sortFn_basic, text: sortFn_text },
})
const helper = createColumnHelper<typeof features, Project>()
const priorities: ProjectPriority[] = ['low', 'normal', 'high', 'critical']
const priorityKeys = {
  low: 'priorityLow',
  normal: 'priorityNormal',
  high: 'priorityHigh',
  critical: 'priorityCritical',
} as const
const priorityColors = { low: 'gray', normal: 'blue', high: 'orange', critical: 'red' }

interface ProjectsTableProps {
  projects: Project[]
  loading: boolean
  scopeKey: string | null
  canWrite: boolean
  canEdit: (id: string) => boolean
  onCreate: () => void
  onEdit: (project: Project) => void
  onDelete: (id: string) => void
  onOpen: (project: Project) => void
}

export function ProjectsTable({
  projects,
  loading,
  scopeKey,
  canWrite,
  canEdit,
  onCreate,
  onEdit,
  onDelete,
  onOpen,
}: ProjectsTableProps) {
  const { t } = useTranslation()
  const [selection, setSelection] = useState<RowSelectionState>({})
  const [onlySelected, setOnlySelected] = useState(false)
  const columns = useMemo(
    () =>
      helper.columns([
        helper.display({
          id: 'select',
          header: '',
          enableHiding: false,
          cell: ({ row }) => (
            <Checkbox
              checked={row.getIsSelected()}
              onChange={row.getToggleSelectedHandler()}
              aria-label={t('projects.selectProject', { name: row.original.name })}
            />
          ),
        }),
        helper.accessor('name', {
          header: t('common.name'),
          enableHiding: false,
          sortFn: 'text',
          cell: (info) => info.getValue(),
        }),
        helper.accessor('external_ref', {
          header: t('projectForm.externalRef'),
          sortFn: 'text',
          cell: (info) => info.getValue() ?? '—',
        }),
        helper.accessor((project) => project.customer_name ?? t('projects.internalCustomer'), {
          id: 'customer',
          header: t('projectForm.customer'),
          filterFn: (row, _columnId, value) =>
            value === 'internal'
              ? row.original.customer_name == null
              : row.original.customer_name != null &&
                value === `customer:${row.original.customer_name}`,
          sortFn: 'text',
          cell: ({ row }) =>
            row.original.customer_name ?? (
              <Text size="sm" c="dimmed">
                {t('projects.internalCustomer')}
              </Text>
            ),
        }),
        helper.accessor('start_date', {
          header: t('projects.startDate'),
          enableGlobalFilter: false,
          sortFn: 'basic',
          cell: (info) => formatDate(info.getValue()),
        }),
        helper.accessor('end_date', {
          header: t('projects.endDate'),
          enableGlobalFilter: false,
          sortFn: 'basic',
          cell: (info) => formatDate(info.getValue()),
        }),
        helper.accessor('priority', {
          header: t('projectForm.priority'),
          filterFn: 'equals',
          enableGlobalFilter: false,
          sortDescFirst: true,
          sortFn: (a, b) =>
            priorities.indexOf(a.original.priority) - priorities.indexOf(b.original.priority),
          cell: (info) => (
            <Badge color={priorityColors[info.getValue()]} variant="light">
              {t(`projectForm.${priorityKeys[info.getValue()]}`)}
            </Badge>
          ),
        }),
        helper.display({
          id: 'actions',
          header: t('common.actions'),
          enableHiding: false,
          cell: ({ row }) => (
            <Group gap="xs" wrap="nowrap">
              <ActionIcon
                variant="subtle"
                color="teal"
                onClick={() => onOpen(row.original)}
                aria-label={t('projects.workPackagesAriaLabel')}
                title={t('projects.workPackagesTitle')}
              >
                <IconPackage size={18} />
              </ActionIcon>
              {canEdit(row.id) && (
                <>
                  <ActionIcon
                    variant="subtle"
                    color="blue"
                    onClick={() => onEdit(row.original)}
                    aria-label={t('projects.editAriaLabel')}
                  >
                    <IconEdit size={18} />
                  </ActionIcon>
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    data-testid={`project-delete-${row.id}`}
                    onClick={() => onDelete(row.id)}
                    aria-label={t('projects.deleteAriaLabel')}
                  >
                    <IconTrash size={18} />
                  </ActionIcon>
                </>
              )}
            </Group>
          ),
        }),
      ]),
    [t, canEdit, onEdit, onDelete, onOpen],
  )
  const table = useTable({
    features,
    data: projects,
    columns,
    getRowId: (project) => project.id,
    globalFilterFn: 'includes',
    state: { rowSelection: selection },
    onRowSelectionChange: setSelection,
  })
  const filteredRows = table.getFilteredRowModel().rows
  // Selection belongs to the visible filtered scope. Hidden or deleted IDs do
  // not spring back into a later selection when a filter is cleared.
  useEffect(() => {
    const ids = new Set(filteredRows.map((row) => row.id))
    setSelection((previous) => {
      const retained = Object.fromEntries(
        Object.entries(previous).filter(([id, selected]) => selected && ids.has(id)),
      )
      return Object.keys(retained).length === Object.keys(previous).length ? previous : retained
    })
  }, [filteredRows])
  useEffect(() => {
    setSelection({})
    setOnlySelected(false)
  }, [scopeKey])
  const customerFilter = table.getColumn('customer')?.getFilterValue()
  const priorityFilter = table.getColumn('priority')?.getFilterValue()
  const selectedCount = filteredRows.filter((row) => row.getIsSelected()).length
  const rows = table.getRowModel().rows.filter((row) => !onlySelected || row.getIsSelected())
  const allSelected = rows.length > 0 && rows.every((row) => row.getIsSelected())
  const customerOptions = useMemo(() => {
    const names = new Set(
      projects
        .map((p) => p.customer_name)
        .filter((name): name is string => typeof name === 'string'),
    )
    // Keep an active filter visible when a folder change or deletion removes
    // its last matching row. The user can still see and clear that filter.
    if (typeof customerFilter === 'string' && customerFilter.startsWith('customer:')) {
      names.add(customerFilter.slice('customer:'.length))
    }
    return [
      { value: 'internal', label: t('projects.internalCustomer') },
      ...[...names]
        .sort((a, b) => a.localeCompare(b))
        .map((name) => ({ value: `customer:${name}`, label: name })),
    ]
  }, [projects, t, customerFilter])

  return (
    <>
      <FilterBar>
        <TextInput
          placeholder={t('projects.searchPlaceholder')}
          aria-label={t('projects.searchPlaceholder')}
          leftSection={<IconSearch size={14} />}
          value={table.state.globalFilter ?? ''}
          onChange={(event) => table.setGlobalFilter(event.currentTarget.value)}
          style={{ flex: 1, minWidth: 180 }}
          disabled={loading}
        />
        <Select
          aria-label={t('projects.customerFilter')}
          placeholder={t('projects.customerFilter')}
          data={customerOptions}
          value={typeof customerFilter === 'string' ? customerFilter : null}
          onChange={(value) => table.getColumn('customer')?.setFilterValue(value ?? undefined)}
          clearable
          searchable
          w={180}
          disabled={loading}
        />
        <Select
          aria-label={t('projects.priorityFilter')}
          placeholder={t('projects.priorityFilter')}
          data={priorities.map((value) => ({
            value,
            label: t(`projectForm.${priorityKeys[value]}`),
          }))}
          value={typeof priorityFilter === 'string' ? priorityFilter : null}
          onChange={(value) => table.getColumn('priority')?.setFilterValue(value ?? undefined)}
          clearable
          w={140}
          disabled={loading}
        />
        <Menu closeOnItemClick={false}>
          <Menu.Target>
            <Button variant="default" leftSection={<IconColumns size={14} />}>
              {t('projects.columns')}
            </Button>
          </Menu.Target>
          <Menu.Dropdown>
            {table
              .getAllLeafColumns()
              .filter((column) => column.getCanHide())
              .map((column) => (
                <Menu.CheckboxItem
                  key={column.id}
                  checked={column.getIsVisible()}
                  onChange={(checked) => column.toggleVisibility(checked)}
                >
                  {typeof column.columnDef.header === 'string'
                    ? column.columnDef.header
                    : column.id}
                </Menu.CheckboxItem>
              ))}
          </Menu.Dropdown>
        </Menu>
        {canWrite && (
          <Button leftSection={<IconPlus size={14} />} onClick={onCreate} size="sm">
            {t('projects.newProject')}
          </Button>
        )}
      </FilterBar>
      {(selectedCount > 0 || onlySelected) && (
        <Group mb="sm" gap="sm">
          <Text size="sm" aria-live="polite">
            {t('projects.selectedCount', { count: selectedCount })}
          </Text>
          <Checkbox
            label={t('projects.showSelected')}
            checked={onlySelected}
            onChange={(event) => setOnlySelected(event.currentTarget.checked)}
          />
          <Button
            size="compact-sm"
            variant="subtle"
            onClick={() => {
              setSelection({})
              setOnlySelected(false)
            }}
          >
            {t('projects.clearSelection')}
          </Button>
        </Group>
      )}
      <Box style={{ overflowX: 'auto' }}>
        <Box miw={900}>
          <DataTable
            loading={loading}
            empty={rows.length === 0}
            emptyMessage={projects.length ? t('projects.noFilterMatch') : t('projects.noProjects')}
            head={table.getHeaderGroups().map((group) => (
              <Table.Tr key={group.id}>
                {group.headers.map((header) => (
                  <Table.Th
                    key={header.id}
                    aria-sort={
                      header.column.getCanSort()
                        ? header.column.getIsSorted() === 'asc'
                          ? 'ascending'
                          : header.column.getIsSorted() === 'desc'
                            ? 'descending'
                            : 'none'
                        : undefined
                    }
                  >
                    {header.id === 'select' ? (
                      <Checkbox
                        aria-label={t('projects.selectVisible')}
                        checked={allSelected}
                        indeterminate={!allSelected && rows.some((row) => row.getIsSelected())}
                        onChange={(event) => {
                          const checked = event.currentTarget.checked
                          setSelection((previous) => {
                            const next = { ...previous }
                            for (const row of rows) {
                              if (checked) next[row.id] = true
                              else delete next[row.id]
                            }
                            return next
                          })
                        }}
                      />
                    ) : header.column.getCanSort() ? (
                      <UnstyledButton fw={600} onClick={header.column.getToggleSortingHandler()}>
                        <Group gap={4} wrap="nowrap">
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {header.column.getIsSorted() === 'asc' ? (
                            <IconArrowUp size={13} />
                          ) : header.column.getIsSorted() === 'desc' ? (
                            <IconArrowDown size={13} />
                          ) : undefined}
                        </Group>
                      </UnstyledButton>
                    ) : (
                      flexRender(header.column.columnDef.header, header.getContext())
                    )}
                  </Table.Th>
                ))}
              </Table.Tr>
            ))}
          >
            {rows.map((row) => (
              <Table.Tr
                key={row.id}
                bg={row.getIsSelected() ? 'var(--mantine-color-blue-light)' : undefined}
              >
                {row.getVisibleCells().map((cell) => (
                  <Table.Td key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
          </DataTable>
        </Box>
      </Box>
    </>
  )
}
