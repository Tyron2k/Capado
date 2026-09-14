/**
 * Displays AI-generated resolution suggestions for a conflict.
 * Each suggestion is a clickable action that applies the fix.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Group, Loader, Stack, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { showErrorNotification } from '../../utils/errorHandling'
import {
  IconArrowRight,
  IconArrowLeft,
  IconPercentage,
  IconSwitchHorizontal,
  IconBulb,
} from '@tabler/icons-react'
import {
  getConflictSuggestions,
  updateAssignment,
  type ConflictSuggestion,
} from '../../api/assignments'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'

interface Props {
  conflictId: string
  onApplied: () => void
}

const ICON_MAP = {
  shift_forward: IconArrowRight,
  shift_backward: IconArrowLeft,
  reduce_allocation: IconPercentage,
  swap_resource: IconSwitchHorizontal,
}

const COLOR_MAP = {
  shift_forward: 'blue',
  shift_backward: 'blue',
  reduce_allocation: 'orange',
  swap_resource: 'teal',
}

function buildDescription(
  s: ConflictSuggestion,
  t: (key: string, params?: Record<string, string | number>) => string,
): string {
  switch (s.type) {
    case 'shift_forward':
      return t('suggestions.descShiftForward', { days: s.shift_days ?? 0 })
    case 'shift_backward':
      return t('suggestions.descShiftBackward', { days: Math.abs(s.shift_days ?? 0) })
    case 'reduce_allocation':
      return t('suggestions.descReduce', { percent: s.new_allocation_percent ?? 0 })
    case 'swap_resource':
      return t('suggestions.descSwap', { name: s.target_resource_name ?? '—' })
    default:
      return s.description
  }
}

export function ConflictSuggestions({ conflictId, onApplied }: Props) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  /**
   * Suggestions fail SILENTLY, and that stays true.
   *
   * They are computed on request and they are optional: a conflict card is useful without them, and a
   * notification saying the suggestions could not be loaded would be noise on a screen already
   * reporting a problem. So the error is swallowed here, deliberately — the one place in this
   * migration where not reporting is the right answer.
   */
  const suggestionsQuery = useQuery({
    queryKey: queryKeys.conflicts.suggestions(conflictId),
    queryFn: () => getConflictSuggestions(conflictId),
  })
  const suggestions: ConflictSuggestion[] = suggestionsQuery.data ?? []
  const loading = suggestionsQuery.isPending

  /**
   * APPLYING A SUGGESTION WRITES AN ASSIGNMENT, so it changes the plan.
   *
   * Four keys: assignments because one changed, conflicts because this one may now be gone, the digest
   * because its findings are derived from both, and planning because the coverage figures are. The
   * hand-written version called `onApplied()` and left it to the parent to decide what to refresh —
   * which meant the answer depended on which screen the card happened to be rendered inside.
   *
   * `onApplied()` is still called: the parent uses it to close the card, which is presentation and not
   * data.
   */
  /** What one applied suggestion needs: the write, plus what to say and how to key the spinner. */
  interface ApplyVars {
    assignmentId: string
    payload: Record<string, unknown>
    description: string
    type: ConflictSuggestion['type']
  }

  const applyMutation = useMutation({
    mutationFn: ({ assignmentId, payload }: ApplyVars) => updateAssignment(assignmentId, payload),
    onSuccess: async (_result, { description }) => {
      notifications.show({
        title: t('common.saved'),
        message: description,
        color: 'green',
      })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.assignments.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
        // The Gantt perspectives DRAW the dates and bars this write moves. Adding it here rather than
        // leaving each screen to remember is the same argument as the rest of this layer.
        queryClient.invalidateQueries({ queryKey: queryKeys.gantt.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.planning.all }),
      ])
      onApplied()
    },
    onError: (error) => showErrorNotification(error, t('common.error'), t('common.genericError')),
  })

  // Which row shows a spinner. The mutation's own variables carry it, so there is no second piece of
  // state to keep in step with the request.
  const applying = applyMutation.isPending
    ? `${applyMutation.variables.assignmentId}${applyMutation.variables.type}`
    : null

  const applySuggestion = (suggestion: ConflictSuggestion) => {
    const payload: Record<string, unknown> = {}

    if (suggestion.type === 'reduce_allocation' && suggestion.new_allocation_percent) {
      payload.allocation_percent = suggestion.new_allocation_percent
    } else if (
      (suggestion.type === 'shift_forward' || suggestion.type === 'shift_backward') &&
      suggestion.shift_days
    ) {
      // A shift needs absolute dates, which this component does not have: updateAssignment takes
      // dates, not a delta. Rather than guess them, the user is told what to do by hand.
      notifications.show({
        title: t('suggestions.shiftHint'),
        message: suggestion.description,
        color: 'blue',
      })
      return
    } else if (suggestion.type === 'swap_resource' && suggestion.target_resource_id) {
      payload.resource_id = suggestion.target_resource_id
    }

    if (Object.keys(payload).length === 0) return
    applyMutation.mutate({
      assignmentId: suggestion.assignment_id,
      payload,
      description: suggestion.description,
      type: suggestion.type,
    })
  }

  if (loading) return <Loader size="xs" />
  if (suggestions.length === 0) return null

  return (
    <Stack gap="xs" mt="sm">
      <Group gap="xs">
        <IconBulb size={14} color="var(--mantine-color-yellow-6)" />
        <Text size="xs" fw={600} c="dimmed">
          {t('suggestions.title')}
        </Text>
      </Group>
      {suggestions.map((s, idx) => {
        const Icon = ICON_MAP[s.type] ?? IconBulb
        const color = COLOR_MAP[s.type] ?? 'gray'
        const key = `${s.assignment_id}-${s.type}-${idx}`
        const label = t(`suggestions.type_${s.type}`)
        const desc = buildDescription(s, t)
        return (
          <Group key={key} gap="xs" wrap="nowrap">
            <Badge size="xs" color={color} variant="light" leftSection={<Icon size={10} />}>
              {label}
            </Badge>
            <Text size="xs" style={{ flex: 1 }}>
              {desc}
            </Text>
            <Button
              size="compact-xs"
              variant="light"
              color={color}
              loading={applying === s.assignment_id + s.type}
              onClick={() => applySuggestion(s)}
            >
              {t('suggestions.apply')}
            </Button>
          </Group>
        )
      })}
    </Stack>
  )
}
