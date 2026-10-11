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
import { Container, Group, Text, Title } from '@mantine/core'

interface PageLayoutProps {
  /** Page title displayed as h2. */
  title: string
  /** Optional elements rendered to the right of the title (e.g. buttons). */
  headerActions?: ReactNode
  description?: string
  children: ReactNode
}

export function PageLayout({ title, headerActions, description, children }: PageLayoutProps) {
  return (
    <Container size="xl" className="capado-page">
      <Group justify="space-between" className="capado-page-header">
        <div>
          <Title order={2} className="capado-page-title">
            {title}
          </Title>
          {description && (
            <Text size="sm" className="capado-page-description">
              {description}
            </Text>
          )}
        </div>
        {headerActions && <Group gap="sm">{headerActions}</Group>}
      </Group>
      {children}
    </Container>
  )
}
