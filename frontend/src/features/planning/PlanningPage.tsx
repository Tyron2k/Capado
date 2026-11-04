/**
 * Planning page with tabs: Overview (unmet requirements + conflicts),
 * Assignments, and Administration (assignment import/export).
 */

import { useRef, useState } from 'react'
import type { ConflictFocus } from './conflictFocus'
import { IconEye, IconList, IconSettings } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import { PageTabs } from '../../components/layout'
import { AssignmentsPanel } from './AssignmentsPanel'
import { PlanningOverviewPanel } from './PlanningOverviewPanel'
import { PlanningAdminPanel } from './PlanningAdminPanel'

export function PlanningPage() {
  const { t } = useTranslation()
  const assignmentsTabRef = useRef<HTMLButtonElement>(null)
  const [tab, setTab] = useState('overview')
  const [assignmentFocus, setAssignmentFocus] = useState<ConflictFocus | null>(null)
  const inspectAssignments = (focus: ConflictFocus) => {
    setAssignmentFocus(focus)
    setTab('assignments')
    assignmentsTabRef.current?.focus()
  }

  return (
    <PageTabs
      title={t('planning.title')}
      value={tab}
      onChange={(value) => setTab(value ?? 'overview')}
      tabs={[
        {
          value: 'overview',
          label: t('planning.tabOverview'),
          icon: IconEye,
          content: (
            <PlanningOverviewPanel active={tab === 'overview'} onAssignments={inspectAssignments} />
          ),
        },
        {
          value: 'assignments',
          buttonRef: assignmentsTabRef,
          label: t('planning.tabAssignments'),
          icon: IconList,
          content: (
            <AssignmentsPanel
              key={JSON.stringify(assignmentFocus)}
              focus={assignmentFocus}
              onClearFocus={() => setAssignmentFocus(null)}
            />
          ),
        },
        {
          value: 'admin',
          label: t('admin.title'),
          icon: IconSettings,
          content: <PlanningAdminPanel />,
        },
      ]}
    />
  )
}
