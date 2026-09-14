/**
 * The digest panel: everything in the plan needing attention, most urgent first.
 *
 * Deliberately plain. The list is already ordered and already suppressed on the backend, so
 * this component's whole job is to render it without adding a second opinion about what
 * matters — grouping or re-sorting here would mean two sources of truth about urgency, and
 * the one on the backend is the one the nightly job will use.
 */

import { useEffect } from 'react'

import { useQuery } from '@tanstack/react-query'
import { Alert, Badge, Card, Group, Skeleton, Stack, Text, Title } from '@mantine/core'
import { IconCheck, IconInfoCircle } from '@tabler/icons-react'
import { getDigest, type Finding, type Severity } from '../../api/digest'
import { showErrorNotification } from '../../utils/errorHandling'
import { formatDate } from '../../utils/date'
import { useTranslation, type Locale } from '../../i18n'
import { queryKeys } from '../../api/queryClient'

const SEVERITY_COLOR: Record<Severity, string> = {
  critical: 'red',
  warning: 'orange',
  info: 'blue',
}

/** Days between two ISO dates, positive for the future. */
function daysUntil(iso: string, from: string): number {
  const target = new Date(`${iso}T00:00:00`)
  const base = new Date(`${from}T00:00:00`)
  return Math.round((target.getTime() - base.getTime()) / 86_400_000)
}

/**
 * Which detail sentence to render for a finding.
 *
 * The backend sends values, not prose, so the singular is this side's problem: German
 * needs "seit einem Tag" where the plural form reads "seit 1 Tagen". Only the kinds that
 * carry a `days` parameter have a `detailOne` variant, and a kind without one can never
 * reach this branch because `params.days` is then undefined — so no existence check is
 * needed and no missing key is ever requested.
 */
function detailKey(finding: Finding): string {
  const suffix = finding.params.days === '1' ? 'detailOne' : 'detail'
  return `digest.finding.${finding.kind}.${suffix}`
}

/** An ISO calendar date, exactly — not a timestamp and not a prefix of one. */
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

/**
 * Format every date in a finding's parameters for the active locale.
 *
 * Selected by the VALUE's shape, not by a list of parameter names. A name list would have
 * to be extended by hand for every new finding kind that carries a date, and the failure
 * would be silent: the sentence renders, just with a raw `2026-09-01` in the middle of it
 * while every other screen shows `01.09.2026`. A shape rule cannot drift.
 *
 * The cost is that a skill or project literally named "2026-09-01" would be reformatted.
 * Accepted knowingly: that is not a name anybody gives a thing, and the alternative trades
 * it for a list that goes stale.
 */
function localiseDates(params: Record<string, string>, locale: Locale): Record<string, string> {
  return Object.fromEntries(
    Object.entries(params).map(([key, value]) => [
      key,
      ISO_DATE.test(value) ? formatDate(value, locale) : value,
    ]),
  )
}

export function DigestPanel() {
  const { t, locale } = useTranslation()

  /**
   * The digest is DOWNSTREAM OF EVERYTHING, which is what makes its key worth having.
   *
   * It is computed on request from qualifications, commitments, dependencies and requirements, so
   * almost any write in the product can change it. Every mutation converted from here on has to ask
   * whether it changed the plan and invalidate `queryKeys.digest.all` if it did — and a key that
   * exists is far likelier to be invalidated than one somebody has to invent at the time.
   *
   * Computed rather than stored on the backend for the same reason, so this cache is the only place
   * staleness can now enter: `staleTime` is deliberately left at the client default of 30s here. A
   * planner reads this screen first, and a digest one action out of date sends them after something
   * already dealt with.
   */
  const digestQuery = useQuery({
    queryKey: queryKeys.digest.today(),
    queryFn: () => getDigest(),
  })
  const digest = digestQuery.data ?? null
  const loading = digestQuery.isPending

  useEffect(() => {
    if (digestQuery.error) {
      showErrorNotification(digestQuery.error, t('common.error'), t('digest.loadFailed'))
    }
  }, [digestQuery.error, t])

  if (loading) {
    return (
      <Card withBorder padding="md">
        <Skeleton height={18} width="30%" mb="sm" />
        <Skeleton height={70} />
      </Card>
    )
  }

  if (!digest) return null

  if (digest.findings.length === 0) {
    return (
      <Card withBorder padding="md">
        <Alert icon={<IconCheck size={16} />} color="green" title={t('digest.allClear')}>
          {t('digest.allClearDetail')}
        </Alert>
      </Card>
    )
  }

  return (
    <Card withBorder padding="md">
      <Group justify="space-between" mb="sm" wrap="nowrap">
        <Title order={4}>{t('digest.title')}</Title>
        <Group gap="xs">
          {(['critical', 'warning', 'info'] as Severity[]).map((severity) =>
            digest.counts[severity] > 0 ? (
              <Badge key={severity} color={SEVERITY_COLOR[severity]} variant="light">
                {digest.counts[severity]} {t(`digest.severity.${severity}`)}
              </Badge>
            ) : null,
          )}
        </Group>
      </Group>

      <Stack gap="xs">
        {digest.findings.map((finding: Finding, index: number) => {
          const days = daysUntil(finding.due, digest.generated_for)
          const shown = localiseDates(finding.params, locale)
          return (
            <Group
              key={`${finding.kind}-${finding.due}-${index}`}
              gap="sm"
              wrap="nowrap"
              align="flex-start"
            >
              <Badge
                color={SEVERITY_COLOR[finding.severity]}
                variant="filled"
                size="sm"
                style={{ flexShrink: 0, minWidth: 74 }}
              >
                {days < 0 ? t('digest.overdue') : t('digest.inDays', { days })}
              </Badge>
              <div>
                <Text size="sm" fw={500}>
                  {t(`digest.finding.${finding.kind}.title`, shown)}
                </Text>
                <Text size="xs" c="dimmed">
                  {t(detailKey(finding), shown)}
                </Text>
              </div>
            </Group>
          )
        })}
      </Stack>

      {digest.suppressed_count > 0 && (
        <Alert
          icon={<IconInfoCircle size={16} />}
          color="gray"
          variant="light"
          mt="sm"
          // Shown, not hidden: a truncated list that looks complete would let somebody
          // conclude there is nothing else, which is the opposite of what a digest is for.
          title={t('digest.truncated', { count: digest.suppressed_count })}
        >
          {t('digest.truncatedDetail')}
        </Alert>
      )}
    </Card>
  )
}
