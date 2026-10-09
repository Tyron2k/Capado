import { masterTableFeatures } from '../../components/table/features'
/** Complete people/equipment lists; feature-specific columns and actions share small table controls. */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Badge, Box, Button, Checkbox, Group, Select, Table, Text, TextInput } from '@mantine/core'
import { IconPlus, IconSearch } from '@tabler/icons-react'
import {
  createColumnHelper,
  flexRender,
  useTable,
  type RowSelectionState,
} from '@tanstack/react-table'
import { ColumnPicker, SortHeader } from '../../components/table/controls'
import { DataTable, FilterBar } from '../../components/layout'
import { useTranslation } from '../../i18n'
import type { FlatResource } from './utils/resourceTableUtils'

const helper = createColumnHelper<typeof masterTableFeatures, FlatResource>()

export function ResourcesTable({
  resources,
  loading,
  hasSites,
  searchLabel,
  emptyLabel,
  createLabel,
  canWrite,
  onCreate,
  onConflicts,
  renderActions,
  testId,
}: {
  resources: FlatResource[]
  loading: boolean
  hasSites: boolean
  searchLabel: string
  emptyLabel: string
  createLabel: string
  canWrite: boolean
  onCreate: () => void
  onConflicts: (resource: FlatResource) => void
  renderActions: (resource: FlatResource) => ReactNode
  testId: string
}) {
  const { t } = useTranslation()
  const [selection, setSelection] = useState<RowSelectionState>({})
  const [onlySelected, setOnlySelected] = useState(false)
  const [conflictsOnly, setConflictsOnly] = useState(false)
  const data = useMemo(
    () => (conflictsOnly ? resources.filter((r) => r.conflict_count > 0) : resources),
    [resources, conflictsOnly],
  )
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
              aria-label={t('tables.selectRow', { name: row.original.name })}
            />
          ),
        }),
        helper.accessor('name', {
          header: t('common.name'),
          sortFn: 'text',
          filterFn: 'includes',
          enableHiding: false,
          cell: ({ getValue }) => <Text size="sm">{getValue()}</Text>,
        }),
        helper.accessor('group_id', {
          id: 'group',
          header: t('resources.group'),
          filterFn: 'equals',
          enableGlobalFilter: false,
          sortFn: (a, b) =>
            (a.original.group_name ?? '').localeCompare(b.original.group_name ?? ''),
          cell: ({ row }) => <Text size="xs">{row.original.group_name || '—'}</Text>,
        }),
        helper.accessor('group_name', {
          id: 'groupSearch',
          header: '',
          enableHiding: false,
          filterFn: 'includes',
        }),
        ...(hasSites
          ? [
              helper.accessor((row) => (row.site_name ? `site:${row.site_name}` : 'none'), {
                id: 'site',
                header: t('resources.site'),
                filterFn: 'equals',
                sortFn: 'text',
                cell: ({ row }) => <Text size="xs">{row.original.site_name || '—'}</Text>,
              }),
            ]
          : []),
        helper.accessor('conflict_count', {
          header: t('conflicts.title'),
          sortFn: 'basic',
          enableGlobalFilter: false,
          cell: ({ row, getValue }) =>
            getValue() > 0 ? (
              <Button
                variant="subtle"
                color="red"
                size="compact-xs"
                onClick={() => onConflicts(row.original)}
                aria-label={t('tables.openConflicts', { name: row.original.name })}
              >
                <Badge color="red" variant="light">
                  {getValue()}
                </Badge>
              </Button>
            ) : null,
        }),
        helper.display({
          id: 'actions',
          header: t('common.actions'),
          enableHiding: false,
          cell: ({ row }) => renderActions(row.original),
        }),
      ]),
    [hasSites, onConflicts, renderActions, t],
  )
  const table = useTable({
    features: masterTableFeatures,
    data,
    columns,
    getRowId: (row) => row.id,
    globalFilterFn: 'includes',
    state: { rowSelection: selection },
    onRowSelectionChange: setSelection,
    initialState: {
      sorting: [
        { id: 'group', desc: false },
        { id: 'name', desc: false },
      ],
      columnVisibility: { groupSearch: false },
    },
  })
  useEffect(() => {
    if (!hasSites) {
      table.setColumnFilters((previous) => {
        const retained = previous.filter((filter) => filter.id !== 'site')
        return retained.length === previous.length ? previous : retained
      })
    }
  }, [hasSites, table])
  const filtered = table.getFilteredRowModel().rows
  const visibleIds = filtered.map((row) => row.id).join('\0')
  useEffect(() => {
    const ids = new Set(visibleIds.split('\0'))
    setSelection((previous) => {
      const next = Object.fromEntries(Object.entries(previous).filter(([id]) => ids.has(id)))
      return Object.keys(next).length === Object.keys(previous).length ? previous : next
    })
  }, [visibleIds])
  const groupFilter = table.getColumn('group')?.getFilterValue()
  const siteFilter = hasSites ? table.getColumn('site')?.getFilterValue() : undefined
  const groups = useMemo(() => {
    const values = new Map(resources.map((r) => [r.group_id, r.group_name || '—']))
    // Retain the active option if an edit removes the last matching row.
    if (typeof groupFilter === 'string' && !values.has(groupFilter))
      values.set(groupFilter, t('tables.missingGroup'))
    return [...values]
      .map(([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [resources, groupFilter, t])
  const siteOptions = new Map(
    resources.map((row) => [
      row.site_name ? `site:${row.site_name}` : 'none',
      row.site_name || t('tables.noSite'),
    ]),
  )
  if (typeof siteFilter === 'string' && !siteOptions.has(siteFilter)) {
    siteOptions.set(siteFilter, siteFilter === 'none' ? t('tables.noSite') : siteFilter.slice(5))
  }
  const rows = table.getRowModel().rows.filter((row) => !onlySelected || row.getIsSelected())
  const count = filtered.filter((row) => row.getIsSelected()).length
  const allSelected = rows.length > 0 && rows.every((row) => row.getIsSelected())
  return (
    <>
      <FilterBar>
        <TextInput
          aria-label={searchLabel}
          placeholder={searchLabel}
          leftSection={<IconSearch size={14} />}
          value={table.state.globalFilter ?? ''}
          onChange={(event) => table.setGlobalFilter(event.currentTarget.value)}
          style={{ flex: 1, minWidth: 180 }}
          disabled={loading}
        />
        <Select
          aria-label={t('tables.groupFilter')}
          placeholder={t('tables.groupFilter')}
          clearable
          searchable
          data={groups}
          value={typeof groupFilter === 'string' ? groupFilter : null}
          onChange={(value) => table.getColumn('group')?.setFilterValue(value ?? undefined)}
          disabled={loading}
          w={190}
        />
        {hasSites && (
          <Select
            aria-label={t('tables.siteFilter')}
            placeholder={t('tables.siteFilter')}
            clearable
            searchable
            data={[...siteOptions].map(([value, label]) => ({ value, label }))}
            value={typeof siteFilter === 'string' ? siteFilter : null}
            onChange={(value) => table.getColumn('site')?.setFilterValue(value ?? undefined)}
            disabled={loading}
            w={190}
          />
        )}
        <Checkbox
          label={t('tables.conflictsOnly')}
          checked={conflictsOnly}
          onChange={(event) => setConflictsOnly(event.currentTarget.checked)}
        />
        <ColumnPicker
          label={t('tables.columns')}
          columns={table
            .getAllLeafColumns()
            .filter((c) => c.getCanHide())
            .map((c) => ({
              id: c.id,
              label: typeof c.columnDef.header === 'string' ? c.columnDef.header : c.id,
              visible: c.getIsVisible(),
              toggle: (visible) => c.toggleVisibility(visible),
            }))}
        />
        {canWrite && (
          <Button leftSection={<IconPlus size={14} />} onClick={onCreate} size="sm">
            {createLabel}
          </Button>
        )}
      </FilterBar>
      {(count > 0 || onlySelected) && (
        <Group mb="sm">
          <Text size="sm" aria-live="polite">
            {t('tables.selectedCount', { count })}
          </Text>
          <Checkbox
            label={t('tables.showSelected')}
            checked={onlySelected}
            onChange={(e) => setOnlySelected(e.currentTarget.checked)}
          />
          <Button
            size="compact-sm"
            variant="subtle"
            onClick={() => {
              setSelection({})
              setOnlySelected(false)
            }}
          >
            {t('tables.clearSelection')}
          </Button>
        </Group>
      )}
      <Box style={{ overflowX: 'auto' }}>
        <Box miw={740}>
          <DataTable
            loading={loading}
            empty={rows.length === 0}
            emptyMessage={resources.length ? t('tables.noFilterMatch') : emptyLabel}
            testId={testId}
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
                        aria-label={t('tables.selectVisible')}
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
                      <SortHeader
                        direction={header.column.getIsSorted()}
                        onClick={() => header.column.toggleSorting()}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                      </SortHeader>
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
