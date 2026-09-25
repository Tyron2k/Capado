/**
 * Displays computed resolution suggestions for a conflict.
 * A suggestion is previewed before it can change the plan.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Group, Loader, Modal, Stack, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { showErrorNotification } from '../../utils/errorHandling'
import {
  IconArrowRight,
  IconArrowLeft,
  IconPercentage,
  IconSwitchHorizontal,
  IconBulb,
  IconClock,
} from '@tabler/icons-react'
import {
  getAssignment,
  getConflictSuggestions,
  previewAssignment,
  updateAssignment,
  type ConflictSuggestion,
} from '../../api/assignments'
import type { AssignmentPreview, AssignmentUpdate } from '../../types/assignment'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { AssignmentPreviewSummary } from '../planning/AssignmentPreviewSummary'
import { patchForSuggestion, previewPayloadForPatch } from './suggestionChange'

interface Props {
  conflictId: string
  onApplied: () => void
}

const ICON_MAP = {
  shift_forward: IconArrowRight,
  shift_backward: IconArrowLeft,
  shift_into_window: IconClock,
  reduce_allocation: IconPercentage,
  swap_resource: IconSwitchHorizontal,
}

const COLOR_MAP = {
  shift_forward: 'blue',
  shift_backward: 'blue',
  shift_into_window: 'blue',
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
    case 'shift_into_window':
      return t('suggestions.descShiftIntoWindow', { time: s.new_start_at?.slice(11, 16) ?? '—' })
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
  const [active, setActive] = useState<{
    suggestion: ConflictSuggestion
    patch: AssignmentUpdate
    result: AssignmentPreview
  } | null>(null)

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
   * Assignments change, conflicts may disappear, and the digest and planning figures derive from both.
   * The hand-written version called `onApplied()` and left it to the parent to decide what to refresh —
   * which meant the answer depended on which screen the card happened to be rendered inside.
   *
   * `onApplied()` is still called: the parent uses it to close the card, which is presentation and not
   * data.
   */
  const previewMutation = useMutation({
    mutationFn: async (suggestion: ConflictSuggestion) => {
      const assignment = await getAssignment(suggestion.assignment_id)
      const patch = patchForSuggestion(suggestion, assignment)
      const result = await previewAssignment(previewPayloadForPatch(assignment, patch))
      return { suggestion, patch, result }
    },
    onSuccess: setActive,
    onError: (error) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.suggestions(conflictId) })
      showErrorNotification(error, t('common.error'), t('common.genericError'))
    },
  })

  const applyMutation = useMutation({
    mutationFn: ({
      suggestion,
      patch,
    }: {
      suggestion: ConflictSuggestion
      patch: AssignmentUpdate
    }) => updateAssignment(suggestion.assignment_id, patch),
    onSuccess: async (_result, { suggestion }) => {
      notifications.show({
        title: t('common.saved'),
        message: buildDescription(suggestion, t),
        color: 'green',
      })
      setActive(null)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.assignments.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.conflicts.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.digest.all }),
        // The Gantt perspectives DRAW the dates and bars this write moves. Adding it here rather than
        // leaving each screen to remember is the same argument as the rest of this layer.
        queryClient.invalidateQueries({ queryKey: queryKeys.gantt.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.planning.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.resources.all }),
      ])
      onApplied()
    },
    onError: (error) => showErrorNotification(error, t('common.error'), t('common.genericError')),
  })

  if (loading) return <Loader size="xs" />
  if (suggestions.length === 0) return null

  return (
    <Stack gap="xs" mt="sm">
      <Modal
        opened={active !== null}
        onClose={() => {
          if (!applyMutation.isPending) setActive(null)
        }}
        title={
          active
            ? t('suggestions.previewAction', { action: buildDescription(active.suggestion, t) })
            : ''
        }
        size="lg"
        closeOnClickOutside={!applyMutation.isPending}
        closeOnEscape={!applyMutation.isPending}
      >
        {active && (
          <Stack gap="md">
            <AssignmentPreviewSummary
              preview={active.result}
              disclaimer={t('suggestions.previewDisclaimer')}
            />
            <Group justify="flex-end">
              <Button
                variant="default"
                onClick={() => setActive(null)}
                disabled={applyMutation.isPending}
              >
                {t('common.cancel')}
              </Button>
              <Button
                onClick={() =>
                  applyMutation.mutate({ suggestion: active.suggestion, patch: active.patch })
                }
                loading={applyMutation.isPending}
              >
                {t('suggestions.apply')}
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
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
              loading={previewMutation.isPending && previewMutation.variables === s}
              disabled={previewMutation.isPending || applyMutation.isPending}
              onClick={() => {
                setActive(null)
                previewMutation.mutate(s)
              }}
            >
              {t('assignmentForm.preview')}
            </Button>
          </Group>
        )
      })}
    </Stack>
  )
}
