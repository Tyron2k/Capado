/**
 * Shared filter bar component for list pages.
 *
 * Provides a consistent horizontal layout for search input, select filters,
 * and segmented controls. Used on Planning, Conflicts, and other list views.
 */

import type { ReactNode } from 'react'
import { Group } from '@mantine/core'

interface FilterBarProps {
  children: ReactNode
}

export function FilterBar({ children }: FilterBarProps) {
  return (
    <Group justify="flex-start" gap="sm" mb="md" wrap="wrap">
      {children}
    </Group>
  )
}
