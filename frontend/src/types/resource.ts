/**
 * TypeScript interfaces for resource groups and resources.
 *
 * Both personal and infrastructure resources share the same shape.
 * They are distinguished by which group (resource_type) they belong to.
 */

// --- Resource Group ---

export interface ResourceGroup {
  id: string
  name: string
  resource_type: 'personal' | 'infrastructure'
  /** Parent group. A work-profile binding on the parent is inherited unless this group has its own. */
  parent_id?: string | null
  created_at: string
  updated_at: string
}

// --- Resource (unified for personal and infrastructure) ---

export interface Resource {
  id: string
  name: string
  group_id: string
  group_name?: string
  /** Site the resource is located at. Null for a single-plant operator, which is not an error. */
  site_id?: string | null
  site_name?: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ResourceCreate {
  name: string
  group_id: string
  site_id?: string | null
}

interface ResourceUpdate {
  name?: string
  group_id?: string
  /**
   * Omit the key to leave the site untouched; send null to REMOVE it. The two are different
   * requests, and the backend distinguishes them — so never spread a default of null into an
   * update payload, or every save would clear the site.
   */
  site_id?: string | null
}

/** Resource with conflict count (returned by tree/list endpoints). */
export interface ResourceListItem {
  id: string
  name: string
  group_id: string
  group_name?: string
  site_id?: string | null
  site_name?: string
  is_active: boolean
  conflict_count: number
}

// --- Legacy aliases for backward compatibility ---

export type PersonalResource = Resource
export type PersonalResourceCreate = ResourceCreate
export type PersonalResourceUpdate = ResourceUpdate
export type InfrastructureResource = Resource
export type InfrastructureResourceCreate = ResourceCreate
export type InfrastructureResourceUpdate = ResourceUpdate
export type PersonalTreeNode = ResourceListItem
export type InfrastructureTreeNode = ResourceListItem

/**
 * Autocomplete result for resource search (personal or infrastructure).
 * Corresponds to backend AutocompleteResultResponse in app/schemas/autocomplete.py.
 */
export interface AutocompleteResult {
  id: string
  name: string
  type: string
  detail: string
}
