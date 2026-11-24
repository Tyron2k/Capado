import type { ConflictSuggestion } from '../../api/assignments'
import type { Assignment, AssignmentUpdate } from '../../types/assignment'
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
