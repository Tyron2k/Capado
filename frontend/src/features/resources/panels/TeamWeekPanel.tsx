/**
 * The team week tab: pick a group, get a printable sheet.
 *
 * The group selection lives here rather than inside the sheet so the sheet itself stays a pure
 * rendering of one group's week — that keeps it usable from anywhere else that already knows which
 * group it means.
 */

import { useEffect, useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { Alert, Skeleton, Stack } from '@mantine/core'
import { IconInfoCircle } from '@tabler/icons-react'
import { getGroups } from '../../../api/resources'
import { showErrorNotification } from '../../../utils/errorHandling'
import { useTranslation } from '../../../i18n'
import { queryKeys } from '../../../api/queryClient'
import { TeamWeekSheet } from '../TeamWeekSheet'

export function TeamWeekPanel() {
  const { t } = useTranslation()
  const [selected, setSelected] = useState<string | null>(null)

  const groupsQuery = useQuery({
    queryKey: queryKeys.resources.groups('personal'),
    queryFn: () => getGroups('personal'),
  })

  const options = useMemo(
    () =>
      groupsQuery.data
        ? groupsQuery.data.map((group) => ({ value: group.id, label: group.name }))
        : null,
    [groupsQuery.data],
  )

  useEffect(() => {
    if (groupsQuery.error) {
      showErrorNotification(groupsQuery.error, t('common.error'), t('teamWeek.loadFailed'))
    }
  }, [groupsQuery.error, t])

  /**
   * Preselect the first group rather than showing an empty state: a foreman opening this tab wants
   * their sheet, not a dropdown to operate first.
   *
   * This USED TO LIVE INSIDE THE `then`, which made it a one-shot: it fired for whatever the first
   * response happened to contain. It is now a condition on the current data, so the preselection also
   * recovers when the group the user had chosen is deleted elsewhere and the list revalidates —
   * previously that left `selected` pointing at a group that no longer existed.
   */
  useEffect(() => {
    if (!options || options.length === 0) return
    if (selected !== null && options.some((o) => o.value === selected)) return
    setSelected(options[0].value)
  }, [options, selected])

  if (options === null) {
    return (
      <Stack>
        <Skeleton height={22} width="30%" />
        <Skeleton height={200} />
      </Stack>
    )
  }

  if (options.length === 0 || selected === null) {
    return (
      <Alert icon={<IconInfoCircle size={16} />} color="blue">
        {t('teamWeek.noGroups')}
      </Alert>
    )
  }

  return <TeamWeekSheet groupId={selected} groupOptions={options} onGroupChange={setSelected} />
}
