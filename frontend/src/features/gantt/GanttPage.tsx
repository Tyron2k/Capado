/**
 * Standalone Gantt page for project and resource timeline visualization.
 */
import { useTranslation } from '../../i18n'
import { PageLayout } from '../../components/layout'
import { GanttSection } from './GanttSection'

export function GanttPage() {
  const { t } = useTranslation()
  return (
    <PageLayout title={t('gantt.title')}>
      <GanttSection />
    </PageLayout>
  )
}
