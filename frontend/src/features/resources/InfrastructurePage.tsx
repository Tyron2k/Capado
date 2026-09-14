/**
 * Infrastructure page: Resources tab (resource list) + Administration tab (groups, skills, import/export).
 */

import { IconBuilding, IconSettings } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import { PageTabs } from '../../components/layout'
import { ResourcesPanel } from './panels/ResourcesPanel'
import { AdminPanel } from './panels/AdminPanel'

export function InfrastructurePage() {
  const { t } = useTranslation()

  return (
    <PageTabs
      title={t('resources.infrastructure')}
      tabs={[
        {
          value: 'resources',
          label: t('resources.overviewTab'),
          icon: IconBuilding,
          content: <ResourcesPanel resourceType="infrastructure" />,
        },
        {
          value: 'admin',
          label: t('admin.title'),
          icon: IconSettings,
          content: <AdminPanel type="infrastructure" />,
        },
      ]}
    />
  )
}
