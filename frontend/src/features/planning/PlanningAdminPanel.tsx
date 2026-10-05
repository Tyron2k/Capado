/**
 * Administration panel for planning: import/export of assignments.
 * Follows the same pattern as ProjectAdminPanel and the resource AdminPanel.
 */

import { Group, Stack, Text } from '@mantine/core'
import { useTranslation } from '../../i18n'
import { SectionHeader } from '../../components/layout'
import { ImportExportBar } from '../resources/ImportExportBar'
import { CsvAreaBar } from '../resources/CsvAreaBar'

/**
 * Renders the Administration tab of the Planning page, exposing bulk
 * import/export of assignments via the shared ImportExportBar.
 */
export function PlanningAdminPanel() {
  const { t } = useTranslation()

  return (
    <Stack gap="xl">
      {/* Import / Export */}
      <div>
        <SectionHeader title={t('admin.importExport')} />
        <Stack gap="md">
          <div>
            <Group justify="space-between" mb={4}>
              <Text size="sm" fw={500}>
                {t('planning.tabAssignments')}
              </Text>
              <ImportExportBar
                exportPath="/api/assignments/export"
                importPath="/api/assignments/import"
                filenameBase="assignments"
                csvOnly
              />
            </Group>
            <Text size="xs" c="dimmed">
              {t('admin.assignmentsCsvHint')}
            </Text>
          </div>
          <Group justify="space-between">
            <Text size="sm" fw={500}>
              {t('importExport.areas.absences')}
            </Text>
            <CsvAreaBar area="absences" />
          </Group>
        </Stack>
      </div>
    </Stack>
  )
}
