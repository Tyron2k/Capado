/**
 * Combined planning overview showing unmet requirements (split by resource type)
 * and active conflicts. Gives planners a single view of what needs attention.
 *
 * Fetches all planning overview data in a single API call via the combined
 * `/api/assignments/planning/overview` endpoint, eliminating the previous
 * 3-4 separate requests.
 */
import { useCallback, useEffect, useMemo } from 'react'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader, Stack } from '@mantine/core'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { getPlanningOverview } from '../../api/assignments'
import { showErrorNotification } from '../../utils/errorHandling'
import { UnmetRequirementsSection } from './UnmetRequirementsAlert'
import { ConflictsSection } from './ConflictsSection'

export function PlanningOverviewPanel() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const overviewQuery = useQuery({
    queryKey: queryKeys.planning.overview(),
    queryFn: ({ signal }) => getPlanningOverview(signal),
  })
  const data = overviewQuery.data ?? null
  const loading = overviewQuery.isPending
  const error = overviewQuery.error !== null

  useEffect(() => {
    if (overviewQuery.error) {
      showErrorNotification(overviewQuery.error, t('common.error'), t('planning.unmetLoadFailed'))
    }
  }, [overviewQuery.error, t])

  /**
   * The reload button becomes an invalidation, not a second fetch path.
   *
   * The difference matters: invalidating means anything else showing these figures refreshes too, and
   * a refetch already in flight is not duplicated. Calling the loader again did neither.
   */
  const reload = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.planning.all })
  }, [queryClient])

  const personalUnmet = useMemo(
    () => (data?.unmet_requirements ?? []).filter((r) => r.resource_type === 'personal'),
    [data],
  )
  const infraUnmet = useMemo(
    () => (data?.unmet_requirements ?? []).filter((r) => r.resource_type === 'infrastructure'),
    [data],
  )

  if (loading) return <Loader size="sm" />

  return (
    <Stack gap="lg">
      <UnmetRequirementsSection
        items={personalUnmet}
        title={t('planning.unmetPersonal')}
        error={error}
        onAssigned={reload}
      />
      <UnmetRequirementsSection
        items={infraUnmet}
        title={t('planning.unmetInfrastructure')}
        error={error}
        onAssigned={reload}
      />
      <ConflictsSection
        conflicts={data?.conflicts ?? []}
        mismatches={data?.mismatched_assignments ?? []}
        onChanged={reload}
      />
    </Stack>
  )
}
