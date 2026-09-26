import type { ConflictSuggestion } from '../../api/assignments'
import type { Assignment, AssignmentCreate, AssignmentUpdate } from '../../types/assignment'
import { addDaysUtc, dayAnchorToIso, startOfDayUtc } from '../../utils/date'

function shiftCalendarDays(value: string, days: number): string {
  const date = dayAnchorToIso(addDaysUtc(startOfDayUtc(value), days))
  if (!date) throw new Error('Invalid assignment date')
  return date + value.slice(10)
}

function parseInstant(value: string): number {
  const result = Date.parse(value)
  if (Number.isNaN(result)) throw new Error('Invalid assignment timestamp')
  return result
}

function suggestedInterval(suggestion: ConflictSuggestion): AssignmentUpdate {
  const { new_start_at, new_end_at } = suggestion
  if (!new_start_at || !new_end_at || parseInstant(new_end_at) <= parseInstant(new_start_at)) {
    throw new Error('Suggestion must include a valid UTC interval')
  }
  return { start_at: new_start_at, end_at: new_end_at }
}

/** Turn a suggestion into the exact partial update that Apply will send. */
export function patchForSuggestion(
  suggestion: ConflictSuggestion,
  assignment: Assignment,
): AssignmentUpdate {
  switch (suggestion.type) {
    case 'reduce_allocation':
      if (suggestion.new_allocation_percent == null) break
      return { allocation_percent: suggestion.new_allocation_percent }
    case 'swap_resource':
      if (!suggestion.target_resource_id) break
      return { resource_id: suggestion.target_resource_id }
    case 'shift_forward':
    case 'shift_backward': {
      const days = suggestion.shift_days
      if (!days || !Number.isInteger(days)) break
      if (assignment.resource_type === 'personal' && assignment.start_date && assignment.end_date) {
        return {
          start_date: shiftCalendarDays(assignment.start_date, days),
          end_date: shiftCalendarDays(assignment.end_date, days),
        }
      }
      if (
        assignment.resource_type === 'infrastructure' &&
        assignment.start_at &&
        assignment.end_at
      ) {
        return suggestedInterval(suggestion)
      }
      break
    }
    case 'shift_into_window': {
      return suggestedInterval(suggestion)
    }
  }
  throw new Error('Suggestion cannot be applied to this assignment')
}

/** The preview endpoint requires the complete resulting assignment, not a partial update. */
export function previewPayloadForPatch(
  assignment: Assignment,
  patch: AssignmentUpdate,
): AssignmentCreate & { assignment_id: string } {
  const resource_id = patch.resource_id ?? assignment.resource_id
  const work_package_id = patch.work_package_id ?? assignment.work_package_id
  const resource_type = patch.resource_type ?? assignment.resource_type
  if (resource_type === 'personal') {
    return {
      assignment_id: assignment.id,
      resource_id,
      resource_type,
      work_package_id,
      start_date: patch.start_date ?? assignment.start_date ?? undefined,
      end_date: patch.end_date ?? assignment.end_date ?? undefined,
      allocation_percent: patch.allocation_percent ?? assignment.allocation_percent ?? undefined,
    }
  }
  return {
    assignment_id: assignment.id,
    resource_id,
    resource_type,
    work_package_id,
    start_at: patch.start_at ?? assignment.start_at ?? undefined,
    end_at: patch.end_at ?? assignment.end_at ?? undefined,
  }
}
