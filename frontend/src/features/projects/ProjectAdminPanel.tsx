/**
 * Administration panel for projects: Templates + Import/Export.
 * Follows the same pattern as the resource AdminPanel.
 */

import { Divider, Group, Stack, Text } from '@mantine/core'
import { useTranslation } from '../../i18n'
import { SectionHeader } from '../../components/layout'
import { ImportExportBar } from '../resources/ImportExportBar'
import { TemplatesPanel } from './TemplatesPanel'

export function ProjectAdminPanel() {
  const { t } = useTranslation()

  return (
    <Stack gap="xl">
      <TemplatesPanel />

      <Divider />

      {/* Import / Export */}
      <div>
        <SectionHeader title={t('admin.importExport')} />
        <Stack gap="md">
          <div>
            <Group justify="space-between" mb={4}>
              <Text size="sm" fw={500}>
                {t('projects.title')}
              </Text>
              <ImportExportBar
                exportPath="/api/projects/export"
                importPath="/api/projects/import"
                filenameBase="projects"
              />
            </Group>
            <Text size="xs" c="dimmed">
              {t('admin.projectsCsvHint')}
            </Text>
          </div>

          <div>
            <Group justify="space-between" mb={4}>
              <Text size="sm" fw={500}>
                {t('templates.title')}
              </Text>
              <ImportExportBar
                exportPath="/api/templates/export"
                importPath="/api/templates/import"
                filenameBase="templates"
              />
            </Group>
            <Text size="xs" c="dimmed">
              {t('admin.templatesCsvHint')}
            </Text>
          </div>
        </Stack>
      </div>
    </Stack>
  )
}
