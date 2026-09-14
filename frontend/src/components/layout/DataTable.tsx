/**
 * Shared data table wrapper with consistent styling.
 *
 * Applies the standard table props used across all pages:
 * `striped`, `highlightOnHover`, `withTableBorder`.
 * Also handles the loading and empty states.
 */

import type { ReactNode } from 'react'
import { Center, Loader, Table, Text } from '@mantine/core'

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
}

export function DataTable({
  loading,
  empty,
  emptyMessage,
  head,
  children,
  testId,
}: DataTableProps) {
  if (loading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    )
  }

  if (empty) {
    return (
      <Text c="dimmed" ta="center" py="xl">
        {emptyMessage ?? 'No data available.'}
      </Text>
    )
  }

  return (
    <Table striped highlightOnHover withTableBorder data-testid={testId}>
      <Table.Thead>{head}</Table.Thead>
      <Table.Tbody>{children}</Table.Tbody>
    </Table>
  )
}
