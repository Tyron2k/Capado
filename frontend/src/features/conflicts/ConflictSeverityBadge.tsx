/**
 * Colored badge for the conflict severity level.
 *
 * Requirements: 4.5, 2.5 (see .kiro/specs/konfliktansicht-verbessern)
 */

import { Badge } from '@mantine/core'
import type { ConflictSeverity } from '../../types/assignment'
import { useTranslation } from '../../i18n'

const SEVERITY_COLOR: Record<ConflictSeverity, string> = {
  low: 'yellow',
  medium: 'orange',
  high: 'red',
}

const SEVERITY_KEY: Record<ConflictSeverity, string> = {
  low: 'conflicts.low',
  medium: 'conflicts.medium',
  high: 'conflicts.high',
}

interface ConflictSeverityBadgeProps {
  severity: ConflictSeverity
}

export function ConflictSeverityBadge({ severity }: ConflictSeverityBadgeProps) {
  const { t } = useTranslation()

  return (
    <Badge
      color={SEVERITY_COLOR[severity]}
      variant="filled"
      data-testid={`severity-badge-${severity}`}
    >
      {t(SEVERITY_KEY[severity])}
    </Badge>
  )
}
