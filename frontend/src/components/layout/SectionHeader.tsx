/**
 * Shared section header within a page or panel.
 *
 * Renders a Title order={4} with optional right-aligned actions.
 * Used for sub-sections within a page (e.g. "Projects" table heading
 * inside the Dashboard, or panel headers inside tabs).
 */

import type { ReactNode } from 'react'
import { Group, Title } from '@mantine/core'

interface SectionHeaderProps {
  /** Section title text. */
  title: string
  /** Optional elements rendered to the right (e.g. add button). */
  actions?: ReactNode
}

export function SectionHeader({ title, actions }: SectionHeaderProps) {
  return (
    <Group justify="space-between" mb="md">
      <Title order={4}>{title}</Title>
      {actions}
    </Group>
  )
}
