/**
 * Shared tabbed page layout.
 *
 * Extends PageLayout with a Mantine Tabs component. Each tab has a label,
 * icon, and content panel. Uses controlled state so that parent re-renders
 * do not reset the active tab.
 */

import { useState, type ReactNode } from 'react'
import { Container, Tabs, Title } from '@mantine/core'
import type { Icon } from '@tabler/icons-react'

export interface TabDefinition {
  /** Unique tab value used for selection. */
  value: string
  /** Displayed tab label. */
  label: string
  /** Tabler icon component rendered in the tab. */
  icon: Icon
  /** Tab panel content. */
  content: ReactNode
}

interface PageTabsProps {
  /** Page title displayed as h2. */
  title: string
  /** Tab definitions. */
  tabs: TabDefinition[]
  /** Which tab is active by default. Defaults to first tab. */
  defaultTab?: string
}

/**
 * Tabbed page shell with controlled tab state.
 * Prevents the active tab from resetting on parent re-renders or
 * notification-triggered context changes.
 */
export function PageTabs({ title, tabs, defaultTab }: PageTabsProps) {
  const [activeTab, setActiveTab] = useState<string | null>(defaultTab ?? tabs[0]?.value ?? null)

  return (
    <Container size="xl">
      <Title order={2} mb="md">
        {title}
      </Title>
      <Tabs value={activeTab} onChange={setActiveTab}>
        <Tabs.List mb="md">
          {tabs.map((tab) => (
            <Tabs.Tab key={tab.value} value={tab.value} leftSection={<tab.icon size={16} />}>
              {tab.label}
            </Tabs.Tab>
          ))}
        </Tabs.List>

        {tabs.map((tab) => (
          <Tabs.Panel key={tab.value} value={tab.value}>
            {tab.content}
          </Tabs.Panel>
        ))}
      </Tabs>
    </Container>
  )
}
