/**
 * Suggestion list for resource assignments.
 * Shows matching personal resources based on qualification (series/skill), time period, and capacity.
 * Uses searchByQualification API for qualification-based filtering.
 * Requirements: 5.4, 5.5, 5.6, 5.8, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
 */

import { useQuery } from '@tanstack/react-query'
import { Badge, Group, Loader, Paper, Stack, Table, Text } from '@mantine/core'
import { DataTable } from '../../components/layout'
import { useDebouncedValue } from '@mantine/hooks'
import { getSuggestions } from '../../api/suggestions'
import { searchByQualification } from '../../api/skills'
import type { ResourceSuggestion, AvailabilityStatus } from '../../types/suggestion'
import type { ResourceType } from '../../types/assignment'
import { toIsoDate, type DateFormValue } from '../../utils/date'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'

interface SuggestionListProps {
  skillId: string | null
  skillAttributeId: string | null
  /** Accepts Mantine date-input values (`YYYY-MM-DD` strings) or `Date` objects. */
  startDate: DateFormValue
  endDate: DateFormValue
  allocationPercent: number
  onSelect: (resourceId: string, resourceType: ResourceType) => void
}

function getAvailabilityColor(status: AvailabilityStatus): string {
  switch (status) {
    case 'available':
      return 'green'
    case 'partially_available':
      return 'yellow'
    case 'unavailable':
      return 'red'
  }
}

function getAvailabilityLabel(status: AvailabilityStatus, t: (key: string) => string): string {
  switch (status) {
    case 'available':
      return t('suggestionList.available')
    case 'partially_available':
      return t('suggestionList.partial')
    case 'unavailable':
      return t('suggestionList.notAvailable')
  }
}

export function SuggestionList({
  skillId,
  skillAttributeId,
  startDate,
  endDate,
  allocationPercent,
  onSelect,
}: SuggestionListProps) {
  const { t } = useTranslation()

  // Debounce all input parameters with 500ms delay
  const [debouncedSkillId] = useDebouncedValue(skillId, 500)
  const [debouncedSkillAttributeId] = useDebouncedValue(skillAttributeId, 500)
  const [debouncedStartDate] = useDebouncedValue(startDate, 500)
  const [debouncedEndDate] = useDebouncedValue(endDate, 500)
  const [debouncedAllocationPercent] = useDebouncedValue(allocationPercent, 500)

  /**
   * DEBOUNCE FIRST, THEN KEY. The debounced values are what reach the query, so the cache holds settled
   * searches rather than one entry per keystroke — and the AbortController that cancelled the previous
   * in-flight request is gone, because a keyed query supersedes its predecessor by construction.
   *
   * The qualification filter is applied CLIENT-SIDE against a second request, deliberately: the
   * availability endpoint knows who is free and the qualification endpoint knows who is able, and no
   * endpoint answers both. Both are awaited inside one queryFn because a half-filtered list is not a
   * useful intermediate state.
   */
  const canSearch = Boolean(debouncedStartDate && debouncedEndDate && debouncedAllocationPercent)

  const searchQuery = useQuery({
    queryKey: queryKeys.conflicts.resourceSearch({
      startDate: debouncedStartDate ? toIsoDate(debouncedStartDate) : '',
      endDate: debouncedEndDate ? toIsoDate(debouncedEndDate) : '',
      allocationPercent: debouncedAllocationPercent ?? 0,
      skillId: debouncedSkillId ?? null,
      skillAttributeId: debouncedSkillAttributeId ?? null,
    }),
    queryFn: async () => {
      const searchParams: { skill_id?: string; skill_attribute_id?: string } = {}
      if (debouncedSkillId) searchParams.skill_id = debouncedSkillId
      if (debouncedSkillAttributeId) searchParams.skill_attribute_id = debouncedSkillAttributeId

      const [suggestionsData, qualificationData] = await Promise.all([
        getSuggestions({
          start_date: toIsoDate(debouncedStartDate!),
          end_date: toIsoDate(debouncedEndDate!),
          allocation_percent: debouncedAllocationPercent!,
        }),
        searchByQualification(searchParams),
      ])

      // With a qualification filter active, only resources that hold it are shown.
      if (debouncedSkillId || debouncedSkillAttributeId) {
        const matchingIds = new Set(qualificationData.map((r) => r.id))
        return suggestionsData.filter((s) => matchingIds.has(s.resource_id))
      }
      return suggestionsData
    },
    enabled: canSearch,
  })

  // A failed search shows the empty state rather than an error: this is a helper list beside a form the
  // user can still fill in by hand, and it is re-run on the next keystroke anyway.
  const suggestions: ResourceSuggestion[] = searchQuery.data ?? []
  const isLoading = canSearch && searchQuery.isPending
  const hasSearched = canSearch && !searchQuery.isPending

  // Don't render anything if required params are missing
  if (!startDate || !endDate || !allocationPercent) {
    return null
  }

  return (
    <Paper p="md" withBorder mt="md">
      <Stack gap="sm">
        <Text fw={600} size="sm">
          {t('suggestionList.title')}
        </Text>

        {isLoading && (
          <Group justify="center" py="md">
            <Loader size="sm" />
            <Text size="sm" c="dimmed">
              {t('suggestionList.loading')}
            </Text>
          </Group>
        )}

        {!isLoading && (
          <DataTable
            empty={hasSearched && suggestions.length === 0}
            emptyMessage={t('suggestionList.noMatch')}
            head={
              <Table.Tr>
                <Table.Th>{t('suggestionList.name')}</Table.Th>
                <Table.Th>{t('suggestionList.qualification')}</Table.Th>
                <Table.Th>{t('suggestionList.availability')}</Table.Th>
                <Table.Th>{t('suggestionList.freeCapacity')}</Table.Th>
              </Table.Tr>
            }
          >
            {suggestions.map((suggestion) => (
              <Table.Tr
                key={suggestion.resource_id}
                onClick={() => onSelect(suggestion.resource_id, 'personal')}
                onKeyDown={(e: React.KeyboardEvent) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onSelect(suggestion.resource_id, 'personal')
                  }
                }}
                tabIndex={0}
                role="button"
                aria-label={suggestion.resource_name}
                style={{ cursor: 'pointer' }}
              >
                <Table.Td>
                  <Text size="sm">{suggestion.resource_name}</Text>
                  <Text size="xs" c="dimmed">
                    {suggestion.department}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{suggestion.qualification_summary || '—'}</Text>
                </Table.Td>
                <Table.Td>
                  <Badge
                    color={getAvailabilityColor(suggestion.availability_status)}
                    variant="light"
                    size="sm"
                  >
                    {getAvailabilityLabel(suggestion.availability_status, t)}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">
                    {t('suggestionList.freePercent', {
                      value: suggestion.average_free_capacity.toFixed(0),
                    })}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </DataTable>
        )}
      </Stack>
    </Paper>
  )
}
