import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Text,
} from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import type { components } from '../../api/generated/schema'
import { getWorkPackageReadiness } from '../../api/assignments'
import { queryKeys } from '../../api/queryClient'
import { useSettings } from '../../context/SettingsContext'
import { useTranslation } from '../../i18n'
import { formatDate, formatDateTime } from '../../utils/date'
import { SectionHeader } from '../../components/layout'
import type { ConflictFocus } from './conflictFocus'
import { UnmetRequirementsSection } from './UnmetRequirementsAlert'
import { ConflictsSection } from './ConflictsSection'

type Package = components['schemas']['PlanningWorkPackage']
type Status = components['schemas']['WorkPackageReadiness']['status']
const COLORS: Record<Status, string> = {
  covered: 'green',
  missing_requirements: 'yellow',
  conflicting: 'red',
  not_fully_assessable: 'gray',
}

export function WorkPackageReadinessPanel({
  packages,
  selected,
  onSelect,
  onAssignments,
  onChanged,
  active = true,
}: {
  packages: Package[]
  active?: boolean
  selected: string | null
  onSelect: (id: string | null) => void
  onAssignments?: (focus: ConflictFocus) => void
  onChanged: () => void
}) {
  const { t, locale } = useTranslation()
  const { settings } = useSettings()
  const query = useQuery({
    queryKey: queryKeys.planning.readiness(selected ?? ''),
    queryFn: ({ signal }) => getWorkPackageReadiness(selected!, signal),
    enabled: Boolean(selected) && active,
    refetchInterval: 60_000,
    refetchOnMount: 'always',
  })
  const data = query.data
  const inspect = (focus: ConflictFocus) => onAssignments?.(focus)
  const detail = () => {
    // A cached successful response must not look current after a failed refresh.
    if (query.isError)
      return (
        <Alert color="red" title={t('readiness.unavailable')}>
          <Text size="sm">{t('readiness.failedCheck')}</Text>
          <Button variant="subtle" onClick={() => void query.refetch()}>
            {t('readiness.retry')}
          </Button>
        </Alert>
      )
    if (query.isFetching || !data)
      return (
        <Group role="status">
          <Loader size="sm" />
          <Text>{t('readiness.checking')}</Text>
        </Group>
      )
    const mismatch = data.assignments.filter((a) => a.skill_mismatch)
    const dimensions = [
      { key: 'personnel', status: data.personnel_status, count: data.personnel_requirements },
      {
        key: 'infrastructure',
        status: data.infrastructure_status,
        count: data.infrastructure_requirements,
      },
      { key: 'qualification', status: data.qualification_status, count: null },
    ]
    return (
      <Stack gap="md" data-testid="work-package-readiness">
        <Group justify="space-between">
          <div>
            <Text fw={600}>
              {data.work_package.project_name} · {data.work_package.name}
            </Text>
            <Text size="sm" c="dimmed">
              {formatDate(data.work_package.start_date, locale)} –{' '}
              {formatDate(data.work_package.end_date, locale)}
            </Text>
          </div>
          <Badge color={COLORS[data.status]}>{t(`readiness.status.${data.status}`)}</Badge>
        </Group>
        <Group justify="space-between">
          <Text size="xs" c="dimmed">
            {t('readiness.checkedAt', {
              time: formatDateTime(data.checked_at, locale, settings.timeZone, true),
            })}
          </Text>
          <Button size="xs" variant="default" onClick={() => void query.refetch()}>
            {t('readiness.refresh')}
          </Button>
        </Group>
        <Text size="xs" c="dimmed">
          {t('readiness.snapshot')}
        </Text>
        <SimpleGrid cols={{ base: 1, sm: 3 }}>
          {dimensions.map((dimension) => (
            <Paper withBorder p="sm" radius="md" key={dimension.key}>
              <Stack gap="xs">
                <Text fw={600} size="sm">
                  {t(`readiness.${dimension.key}`)}
                </Text>
                <Badge color={COLORS[dimension.status]} variant="light">
                  {t(`readiness.status.${dimension.status}`)}
                </Badge>
                {dimension.count !== null && (
                  <Text size="xs" c="dimmed">
                    {t('readiness.requirementCount', { count: dimension.count })}
                  </Text>
                )}
              </Stack>
            </Paper>
          ))}
        </SimpleGrid>
        {data.limits.length > 0 && (
          <Alert color="blue" title={t('readiness.scope')}>
            <Stack gap={4}>
              {data.limits.map((limit) => (
                <Text size="sm" key={limit}>
                  {t(`readiness.limits.${limit}`)}
                </Text>
              ))}
            </Stack>
          </Alert>
        )}
        {data.supply_gaps.map((gap) => (
          <Alert color="orange" key={gap.resource_id} title={gap.resource_name}>
            <Text size="sm">{t('readiness.noSupply', { day: formatDate(gap.day, locale) })}</Text>
            {onAssignments && (
              <Button
                size="xs"
                variant="subtle"
                onClick={() =>
                  inspect({ workPackageId: data.work_package.id, resourceId: gap.resource_id })
                }
              >
                {t('readiness.inspectBookings')}
              </Button>
            )}
          </Alert>
        ))}
        {(['personal', 'infrastructure'] as const).map((kind) => {
          const items = data.unmet_requirements.filter((r) => r.resource_type === kind)
          if (
            items.length === 0 ||
            (kind === 'personal' && data.limits.includes('no_standard_profile'))
          )
            return null
          return (
            <UnmetRequirementsSection
              key={kind}
              items={items}
              error={false}
              onAssigned={onChanged}
              title={t(
                kind === 'personal' ? 'planning.unmetPersonal' : 'planning.unmetInfrastructure',
              )}
            />
          )
        })}
        {mismatch.length > 0 && (
          <>
            <Text size="sm">{t('readiness.qualificationRule')}</Text>
            <ConflictsSection conflicts={[]} mismatches={mismatch} onChanged={onChanged} />
          </>
        )}
        {data.conflicts.length > 0 && (
          <Stack gap="xs">
            <SectionHeader title={t('readiness.currentConflicts')} />
            {data.conflicts.map((conflict, index) => (
              <Paper withBorder p="sm" radius="md" key={`${conflict.resource_id}-${index}`}>
                <Group justify="space-between" align="flex-start">
                  <Stack gap={4}>
                    <Text fw={600}>{conflict.resource_name}</Text>
                    <Text size="sm">{t(`readiness.causes.${conflict.cause}`)}</Text>
                    <Text size="xs" c="dimmed">
                      {formatDate(conflict.start_date, locale)} –{' '}
                      {formatDate(conflict.end_date, locale)} ·{' '}
                      {t('readiness.affectedBookings', { count: conflict.assignment_ids.length })}
                    </Text>
                  </Stack>
                  {onAssignments && (
                    <Button
                      size="xs"
                      variant="light"
                      onClick={() => inspect({ resourceId: conflict.resource_id })}
                    >
                      {t('readiness.inspectResourceBookings')}
                    </Button>
                  )}
                </Group>
              </Paper>
            ))}
          </Stack>
        )}
        {onAssignments && (
          <Button
            variant="default"
            onClick={() => inspect({ workPackageId: data.work_package.id })}
          >
            {t('readiness.inspectBookings')}
          </Button>
        )}
      </Stack>
    )
  }
  return (
    <Stack gap="md">
      <SectionHeader title={t('readiness.title')} />
      <Select
        label={t('readiness.selectPackage')}
        placeholder={t('readiness.choosePackage')}
        data={packages.map((wp) => ({ value: wp.id, label: `${wp.project_name} · ${wp.name}` }))}
        value={selected}
        onChange={onSelect}
        searchable
        clearable
        nothingFoundMessage={t('readiness.noPackages')}
      />
      {selected ? (
        detail()
      ) : (
        <Text size="sm" c="dimmed">
          {t('readiness.introduction')}
        </Text>
      )}
    </Stack>
  )
}
