import type { components } from '../api/generated/schema'

/**
 * TypeScript interfaces for resource groups and resources.
 *
 * Both personal and infrastructure resources share the same shape.
 * They are distinguished by which group (resource_type) they belong to.
 */

// --- Resource Group ---

export type ResourceGroup = components['schemas']['ResourceGroupResponse']

// --- Resource (unified for personal and infrastructure) ---

export type Resource = components['schemas']['ResourceResponse']

export type ResourceCreate = components['schemas']['ResourceCreate']

/** Resource with conflict count (returned by tree/list endpoints). */
export type ResourceListItem = components['schemas']['ResourceListItemResponse']

// --- Legacy aliases for backward compatibility ---

export type PersonalResource = Resource
export type InfrastructureResource = Resource
export type PersonalTreeNode = ResourceListItem
export type InfrastructureTreeNode = ResourceListItem

/**
 * Autocomplete result for resource search (personal or infrastructure).
 * Corresponds to backend AutocompleteResultResponse in app/schemas/autocomplete.py.
 */
export type AutocompleteResult = components['schemas']['AutocompleteResultResponse']
