import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Text } from '@mantine/core'
import apiClient from '../../api/client'
import { queryKeys } from '../../api/queryClient'
import { useTranslation } from '../../i18n'

interface CheckStatus {
  last_checked_at: string | null
  status: 'never' | 'running' | 'succeeded' | 'failed'
  stale: boolean
  enabled: boolean
}

/** Poll while visible, and refresh derived views after a completed full check. */
export function ConflictCheckStatus() {
  const { t } = useTranslation()
  const client = useQueryClient()
  const previous = useRef<string | null | undefined>(undefined)
  const { data, isError } = useQuery({
    queryKey: queryKeys.conflicts.checkStatus(),
    queryFn: async ({ signal }) =>
      (await apiClient.get<CheckStatus>('/api/conflicts/check-status', { signal })).data,
    refetchInterval: 60_000,
  })
  useEffect(() => {
    if (!data) return
    if (previous.current !== undefined && previous.current !== data.last_checked_at) {
      for (const queryKey of [
        queryKeys.conflicts.all,
        queryKeys.planning.all,
        queryKeys.gantt.all,
        queryKeys.dashboard.all,
      ]) {
        void client.invalidateQueries({ queryKey })
      }
    }
    previous.current = data.last_checked_at
  }, [data, client])

  const checked = data?.last_checked_at
    ? t('conflictCheck.lastChecked', { time: new Date(data.last_checked_at).toLocaleString() })
    : t('conflictCheck.never')
  const warning = isError
    ? t('conflictCheck.unavailable')
    : data && !data.enabled
      ? t('conflictCheck.disabled')
      : data?.status === 'failed'
        ? t('conflictCheck.failed')
        : data?.stale && data.status !== 'never'
          ? t('conflictCheck.overdue')
          : null
  return (
    <Text size="xs" c={warning ? 'orange' : 'dimmed'} role={warning ? 'status' : undefined}>
      {data ? checked : t('conflictCheck.loading')}
      {warning && ` · ${warning}`}
      {data?.status === 'running' && ` · ${t('conflictCheck.running')}`}
    </Text>
  )
}
