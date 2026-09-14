/**
 * Projects page: Projects tab (CRUD) + Administration tab (Templates).
 * Follows the same structure as People and Infrastructure pages.
 */

import { IconBriefcase, IconBuilding, IconSettings } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import { PageTabs } from '../../components/layout'
import { ProjectsPanel } from './ProjectsPanel'
import { ProjectAdminPanel } from './ProjectAdminPanel'
import { CustomerPanel } from './panels/CustomerPanel'

export function ProjectsPage() {
  const { t } = useTranslation()

  return (
    <PageTabs
      title={t('projects.title')}
      tabs={[
        {
          value: 'projects',
          label: t('projects.tabProjects'),
          icon: IconBriefcase,
          content: <ProjectsPanel />,
        },
        {
          value: 'customers',
          label: t('customers.title'),
          icon: IconBuilding,
          content: <CustomerPanel />,
        },
        {
          value: 'admin',
          label: t('admin.title'),
          icon: IconSettings,
          content: <ProjectAdminPanel />,
        },
      ]}
    />
  )
}
