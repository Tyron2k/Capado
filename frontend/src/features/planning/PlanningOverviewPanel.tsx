/**
 * Combined planning overview showing unmet requirements (split by resource type)
 * and active conflicts. Gives planners a single view of what needs attention.
 *
 * Fetches all planning overview data in a single API call via the combined
 * `/api/assignments/planning/overview` endpoint, eliminating the previous
 * 3-4 separate requests.
 */
import { ConflictCheckStatus } from '../conflicts/ConflictCheckStatus'
import { useCallback, useEffect, useMemo } from 'react'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Alert, Button, Loader, Stack } from '@mantine/core'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { getPlanningOverview } from '../../api/assignments'
import { showErrorNotification } from '../../utils/errorHandling'
import { UnmetRequirementsSection } from './UnmetRequirementsAlert'
import { ConflictsSection } from './ConflictsSection'
import { WorkPackageReadinessPanel } from './WorkPackageReadinessPanel'
import type { ConflictFocus } from './conflictFocus'
import { parseConflictFocus } from './conflictFocus'

export function PlanningOverviewPanel({
  onAssignments,
  active = true,
}: {
  onAssignments?: (focus: ConflictFocus) => void
  active?: boolean
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const conflictFocus = parseConflictFocus(searchParams)

  const clearConflictFocus = useCallback(() => {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous)
      next.delete('project')
      next.delete('work_package')
      next.delete('resource')
      return next
    })
  }, [setSearchParams])

  const overviewQuery = useQuery({
    queryKey: queryKeys.planning.overview(),
    refetchInterval: 60_000,
    enabled: active,
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
  if (error)
    return (
      <Alert color="red" title={t('readiness.unavailable')}>
        <Button variant="subtle" onClick={reload}>
          {t('readiness.retry')}
        </Button>
      </Alert>
    )
  const selected = searchParams.get('assess')

  return (
    <Stack gap="lg">
      <WorkPackageReadinessPanel
        active={active}
        packages={data?.work_packages ?? []}
        selected={selected}
        onSelect={(id) =>
          setSearchParams((previous) => {
            const next = new URLSearchParams(previous)
            if (id) next.set('assess', id)
            else next.delete('assess')
            next.delete('work_package')
            next.delete('project')
            next.delete('resource')
            return next
          })
        }
        onAssignments={onAssignments}
        onChanged={reload}
      />
      {!selected && (
        <>
          <ConflictCheckStatus />
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
            focus={conflictFocus}
            onClearFocus={clearConflictFocus}
          />
        </>
      )}
    </Stack>
  )
}
