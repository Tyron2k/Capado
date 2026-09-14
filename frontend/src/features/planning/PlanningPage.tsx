/**
 * Planning page with tabs: Overview (unmet requirements + conflicts),
 * Assignments, and Administration (assignment import/export).
 */

import { IconEye, IconList, IconSettings } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import { PageTabs } from '../../components/layout'
import { AssignmentsPanel } from './AssignmentsPanel'
import { PlanningOverviewPanel } from './PlanningOverviewPanel'
import { PlanningAdminPanel } from './PlanningAdminPanel'

export function PlanningPage() {
  const { t } = useTranslation()

  return (
    <PageTabs
      title={t('planning.title')}
      tabs={[
        {
          value: 'overview',
          label: t('planning.tabOverview'),
          icon: IconEye,
          content: <PlanningOverviewPanel />,
        },
        {
          value: 'assignments',
          label: t('planning.tabAssignments'),
          icon: IconList,
          content: <AssignmentsPanel />,
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
