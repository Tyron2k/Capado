/**
 * Administration panel combining Groups, Skills management and centralized
 * import/export with format descriptions.
 */

import { Divider, Group, Stack, Text } from '@mantine/core'
import { useTranslation } from '../../../i18n'
import { SectionHeader } from '../../../components/layout'
import { ImportExportBar } from '../ImportExportBar'
import { GroupsPanel } from './GroupsPanel'
import { SkillsPanel } from './SkillsPanel'

interface AdminPanelProps {
  type: 'personal' | 'infrastructure'
}

export function AdminPanel({ type }: AdminPanelProps) {
  const { t } = useTranslation()

  const resourceExportPath =
    type === 'personal' ? '/api/personnel/export' : '/api/infrastructure/export'
  const resourceImportPath =
    type === 'personal' ? '/api/personnel/import' : '/api/infrastructure/import'
  const resourceFilename = type === 'personal' ? 'personnel' : 'infrastructure'

  return (
    <Stack gap="xl">
      <GroupsPanel resourceType={type} />

      <Divider />

      <SkillsPanel resourceType={type} />

      <Divider />

      {/* Import / Export */}
      <div>
        <SectionHeader title={t('admin.importExport')} />
        <Stack gap="md">
          {/* Resources (includes skills inline) */}
          <div>
            <Group justify="space-between" mb={4}>
              <Text size="sm" fw={500}>
                {type === 'personal' ? t('people.employees') : t('infrastructure.resources')}
              </Text>
              <ImportExportBar
                exportPath={resourceExportPath}
                importPath={resourceImportPath}
                filenameBase={resourceFilename}
              />
            </Group>
            <Text size="xs" c="dimmed">
              {type === 'personal' ? t('admin.peopleCsvHint') : t('admin.infrastructureCsvHint')}
            </Text>
          </div>
        </Stack>
      </div>
    </Stack>
  )
}
