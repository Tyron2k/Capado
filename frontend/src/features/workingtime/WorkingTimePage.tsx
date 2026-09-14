/**
 * Working-time configuration page at /working-time.
 *
 * The supply side of the capacity model in one place: sites (which own the
 * holiday calendar), calendar exceptions, and week profiles.
 *
 * Infrastructure availability windows are deliberately NOT here. They belong to a
 * single machine or track rather than to the organisation, so they are edited on
 * the infrastructure resource itself — putting them behind a global tab would mean
 * picking a resource from a list of hundreds before editing anything.
 */

import { IconBuildingFactory2, IconCalendarOff, IconClockHour4 } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import { PageTabs, type TabDefinition } from '../../components/layout'
import { HolidaysTab } from './HolidaysTab'
import { SitesTab } from './SitesTab'
import { WeekProfilesTab } from './WeekProfilesTab'

export function WorkingTimePage() {
  const { t } = useTranslation()

  const tabs: TabDefinition[] = [
    {
      value: 'profiles',
      label: t('workingTime.tabs.profiles'),
      icon: IconClockHour4,
      content: <WeekProfilesTab />,
    },
    {
      value: 'holidays',
      label: t('workingTime.tabs.holidays'),
      icon: IconCalendarOff,
      content: <HolidaysTab />,
    },
    {
      value: 'sites',
      label: t('workingTime.tabs.sites'),
      icon: IconBuildingFactory2,
      content: <SitesTab />,
    },
  ]

  return <PageTabs title={t('workingTime.title')} tabs={tabs} defaultTab="profiles" />
}
