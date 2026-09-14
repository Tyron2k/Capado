/**
 * People page: Employees tab (resource list) + Administration tab (groups, skills, import/export).
 */

import { IconCalendarWeek, IconSettings, IconUsers } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import { PageTabs } from '../../components/layout'
import { ResourcesPanel } from './panels/ResourcesPanel'
import { AdminPanel } from './panels/AdminPanel'
import { TeamWeekPanel } from './panels/TeamWeekPanel'

export function PeoplePage() {
  const { t } = useTranslation()

  return (
    <PageTabs
      title={t('resources.personal')}
      tabs={[
        {
          value: 'people',
          label: t('resources.overviewTab'),
          icon: IconUsers,
          content: <ResourcesPanel resourceType="personal" />,
        },
        {
          value: 'team-week',
          label: t('teamWeek.tab'),
          icon: IconCalendarWeek,
          content: <TeamWeekPanel />,
        },
        {
          value: 'admin',
          label: t('admin.title'),
          icon: IconSettings,
          content: <AdminPanel type="personal" />,
        },
      ]}
    />
  )
}
