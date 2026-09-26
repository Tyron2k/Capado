import { Select, Stack } from '@mantine/core'
import type { ComponentProps } from 'react'
import { DateTimeField } from './DateField'
import { instantToLocalDateTime, localDateTimeToUtc, localTimeChoices } from '../utils/date'
import { useTranslation } from '../i18n'

type Props = Omit<ComponentProps<typeof DateTimeField>, 'value' | 'onChange'> & {
  value?: string | Date | null
  onChange: (value: string | null) => void
  timeZone: string
}

/** Keep resolved instants in form state; ask explicitly when a clock time occurs twice. */
export function ZonedDateTimeField({ value, onChange, timeZone, ...props }: Props) {
  const { t } = useTranslation()
  const text = typeof value === 'string' ? value : ''
  const choices = text ? localTimeChoices(text, timeZone) : []
  const instant = text ? localDateTimeToUtc(text, timeZone) : null
  return (
    <Stack gap="xs">
      <DateTimeField
        {...props}
        description={timeZone}
        value={text ? instantToLocalDateTime(text, timeZone).replace('T', ' ') : null}
        onChange={(local) =>
          onChange(local ? (localDateTimeToUtc(local, timeZone) ?? local) : null)
        }
      />
      {choices.length > 1 && (
        <Select
          label={t('assignmentForm.repeatedTime')}
          data={choices}
          value={instant}
          onChange={(choice) => {
            if (choice) onChange(choice)
          }}
          allowDeselect={false}
          required
        />
      )}
    </Stack>
  )
}
