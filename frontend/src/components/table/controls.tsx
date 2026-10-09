/** Small shared controls used by the project and resource tables. Columns stay in each feature. */
import type { ReactNode } from 'react'
import { Button, Group, Menu, UnstyledButton } from '@mantine/core'
import { IconArrowDown, IconArrowUp, IconColumns } from '@tabler/icons-react'

export function ColumnPicker({
  label,
  columns,
}: {
  label: string
  columns: { id: string; label: string; visible: boolean; toggle: (visible: boolean) => void }[]
}) {
  return (
    <Menu closeOnItemClick={false}>
      <Menu.Target>
        <Button variant="default" leftSection={<IconColumns size={14} />}>
          {label}
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        {columns.map((column) => (
          <Menu.CheckboxItem key={column.id} checked={column.visible} onChange={column.toggle}>
            {column.label}
          </Menu.CheckboxItem>
        ))}
      </Menu.Dropdown>
    </Menu>
  )
}

export function SortHeader({
  children,
  direction,
  onClick,
}: {
  children: ReactNode
  direction: false | 'asc' | 'desc'
  onClick: () => void
}) {
  return (
    <UnstyledButton fw={600} onClick={onClick}>
      <Group gap={4} wrap="nowrap">
        {children}
        {direction === 'asc' ? (
          <IconArrowUp size={13} />
        ) : direction === 'desc' ? (
          <IconArrowDown size={13} />
        ) : undefined}
      </Group>
    </UnstyledButton>
  )
}
