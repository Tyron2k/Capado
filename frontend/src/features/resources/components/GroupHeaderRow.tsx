/**
 * Renders a group header row spanning all table columns.
 * Used as a visual separator in grouped DataTables to divide resources
 * by department (People) or infra group (Infrastructure).
 */

import { Table } from '@mantine/core'

interface GroupHeaderRowProps {
  /** The name of the group (department or infra group). */
  groupName: string
  /** Number of resources in this group. */
  count: number
  /** Number of columns the header should span. */
  colSpan: number
}

/**
 * Renders a full-width table row acting as a group separator.
 * Spans all columns and displays the group name with a resource count in bold.
 */
export function GroupHeaderRow({ groupName, count, colSpan }: GroupHeaderRowProps) {
  return (
    <Table.Tr
      style={{
        backgroundColor: 'var(--mantine-color-gray-1)',
        borderBottom: '2px solid var(--mantine-color-gray-3)',
      }}
      data-testid={`group-header-${groupName}`}
    >
      <Table.Td colSpan={colSpan} fw={600} py="xs" px="sm">
        {groupName} ({count})
      </Table.Td>
    </Table.Tr>
  )
}
