import { Alert, Stack, Text } from '@mantine/core'
import type { AssignmentPreview } from '../../types/assignment'
import { useTranslation } from '../../i18n'
import { formatDate } from '../../utils/date'

interface Props {
  preview: AssignmentPreview
  disclaimer?: string
}

export function AssignmentPreviewSummary({ preview, disclaimer }: Props) {
  const { t } = useTranslation()

  return (
    <Alert title={t('assignmentForm.previewTitle')} color="blue" aria-live="polite">
      <Stack gap="sm">
        <Text size="xs">{disclaimer ?? t('assignmentForm.previewDisclaimer')}</Text>
        {preview.resources.map((resource) => (
          <Stack key={resource.resource_id} gap={4}>
            <Text fw={600} size="sm">
              {resource.resource_name}
            </Text>
            <Text size="sm">
              {t('assignmentForm.previewConflicts', {
                before: resource.conflicts_before.length,
                after: resource.conflicts_after.length,
              })}
            </Text>
            {resource.conflicts_after.slice(0, 5).map((conflict, index) => (
              <Text key={`${conflict.cause}-${conflict.start_date}-${index}`} size="xs">
                {t(`assignmentForm.conflictCause.${conflict.cause}`)}:{' '}
                {formatDate(conflict.start_date)}–{formatDate(conflict.end_date)}
              </Text>
            ))}
            {resource.conflicts_after.length > 5 && (
              <Text size="xs">
                {t('assignmentForm.moreConflicts', {
                  count: resource.conflicts_after.length - 5,
                })}
              </Text>
            )}
            {resource.resource_type === 'personal' && (
              <Text size="xs">
                {t('assignmentForm.changedDays', { count: resource.capacity_days.length })}
              </Text>
            )}
            {resource.capacity_days.slice(0, 5).map((day) => (
              <Text key={day.date} size="xs">
                {formatDate(day.date)}: {Math.round(day.assigned_before_percent)}% →{' '}
                {Math.round(day.assigned_after_percent)}% ({t('assignmentForm.available')}:{' '}
                {Math.round(day.available_percent)}%)
              </Text>
            ))}
            {resource.capacity_days.length > 5 && (
              <Text size="xs">
                {t('assignmentForm.moreDays', { count: resource.capacity_days.length - 5 })}
              </Text>
            )}
          </Stack>
        ))}
      </Stack>
    </Alert>
  )
}
