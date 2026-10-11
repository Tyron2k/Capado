/**
 * Shared data table wrapper with consistent styling.
 *
 * Opaque surface, local horizontal scrolling and optional row density/striping.
 * Also handles loading and empty states without changing feature-specific table state.
 */

import type { ReactNode } from 'react'
import { Center, Loader, Stack, Table, Text } from '@mantine/core'
import { IconInbox } from '@tabler/icons-react'

export type TableDensity = 'comfortable' | 'compact'

interface DataTableProps {
  /** Whether data is currently loading. */
  loading?: boolean
  /** Whether the dataset is empty (after loading). */
  empty?: boolean
  /** Message shown when the dataset is empty. */
  emptyMessage?: string
  /** Table header row(s). */
  head: ReactNode
  /** Table body rows. */
  children: ReactNode
  /** Optional data-testid for the table element. */
  testId?: string
  density?: TableDensity
  minWidth?: number
  striped?: boolean
}

export function DataTable({
  loading,
  empty,
  emptyMessage,
  head,
  children,
  testId,
  density = 'comfortable',
  minWidth = 640,
  striped = false,
}: DataTableProps) {
  if (loading) {
    return (
      <Center py="xl" mih={180} className="capado-surface" role="status">
        <Loader />
      </Center>
    )
  }

  if (empty) {
    return (
      <Center py="xl" mih={180} className="capado-surface">
        <Stack gap="sm" align="center">
          <IconInbox size={32} stroke={1.3} color="var(--capado-muted)" aria-hidden="true" />
          <Text c="dimmed" ta="center">
            {emptyMessage ?? 'No data available.'}
          </Text>
        </Stack>
      </Center>
    )
  }

  return (
    <Table.ScrollContainer
      minWidth={minWidth}
      type="native"
      className="capado-data-table capado-surface"
    >
      <Table
        striped={striped}
        highlightOnHover
        data-testid={testId}
        data-density={density}
        verticalSpacing={density === 'compact' ? 4 : 12}
      >
        <Table.Thead>{head}</Table.Thead>
        <Table.Tbody>{children}</Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}
