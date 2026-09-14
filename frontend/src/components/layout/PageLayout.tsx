/**
 * Shared page layout shell.
 *
 * Provides the consistent page structure used across all feature pages:
 * - Container with `size="xl"`
 * - Title with `order={2}` and `mb="md"`
 * - Optional right-aligned header actions (buttons, controls)
 * - Children rendered below
 */

import type { ReactNode } from 'react'
import { Container, Group, Title } from '@mantine/core'

interface PageLayoutProps {
  /** Page title displayed as h2. */
  title: string
  /** Optional elements rendered to the right of the title (e.g. buttons). */
  headerActions?: ReactNode
  children: ReactNode
}

export function PageLayout({ title, headerActions, children }: PageLayoutProps) {
  return (
    <Container size="xl">
      <Group justify="space-between" mb="md">
        <Title order={2}>{title}</Title>
        {headerActions && <Group gap="sm">{headerActions}</Group>}
      </Group>
      {children}
    </Container>
  )
}
