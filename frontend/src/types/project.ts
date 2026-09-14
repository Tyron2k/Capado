/**
 * TypeScript interfaces for projects and project folders.
 * Corresponds to the backend schemas in app/schemas/project.py
 */

/**
 * An optional grouping for projects.
 *
 * A folder is deliberately not a project: it has no dates and carries no work, so
 * deleting one only unfiles what was inside it (ADR-008).
 */
/**
 * Cross-project urgency, distinct from `position` which orders within a folder.
 *
 * Four named levels rather than a free integer: integers invite duelling ranks nobody can
 * read, while a small ordered set is legible at a glance.
 */
export type ProjectPriority = 'low' | 'normal' | 'high' | 'critical'

export interface ProjectFolder {
  id: string
  name: string
  /** Owning folder, or null for a top-level one. Folders may nest. */
  parent_id: string | null
  position: number
  /** The grouping's own identifier — an order number where a folder is an order. */
  external_ref: string | null
  created_at: string
  updated_at: string
  /** The customer for everything in this folder; inherited by projects and sub-folders. */
  customer_id: string | null
  /** Resolved name, for display without a second lookup. */
  customer_name?: string | null
}

export interface ProjectFolderCreate {
  name: string
  parent_id?: string | null
  position?: number
  external_ref?: string | null
  customer_id?: string | null
}

export interface ProjectFolderUpdate {
  name?: string
  /** Send null to move the folder to the top level; omit to leave it unchanged. */
  parent_id?: string | null
  position?: number
  external_ref?: string | null
  customer_id?: string | null
}

/** What deleting a folder did. Reported so the user sees their projects survived. */
export interface ProjectFolderDeleteResult {
  projects_unfiled: number
  subfolders_moved: number
}

export interface Project {
  id: string
  name: string
  /** Optional grouping. null means unfiled, which is the normal default. */
  folder_id: string | null
  /** Order within the folder. Units of an order are worked through in sequence. */
  position: number
  /** Identifier from whatever system the customer already uses (unit number, serial). */
  external_ref: string | null
  start_date: string // ISO date string (YYYY-MM-DD)
  /** What is PLANNED. Distinct from committed_delivery_date, which is what was promised. */
  end_date: string // ISO date string (YYYY-MM-DD)
  /**
   * What was PROMISED, or null when nothing was.
   *
   * Separate from end_date on purpose: one field cannot hold both a commitment and a
   * plan, because the moment they differ is the moment that matters.
   */
  committed_delivery_date: string | null
  /** Who the work is for, or null for internal work. */
  /** Set only when this project overrides its folder. Usually null — read customer_name. */
  customer_id: string | null
  /** The RESOLVED name, folder inheritance included. */
  customer_name: string | null
  /** True when the name came from a folder rather than from the project itself. */
  customer_inherited: boolean
  priority: ProjectPriority
  created_at: string
  updated_at: string
}

export interface ProjectCreate {
  name: string
  start_date: string // ISO date string (YYYY-MM-DD)
  end_date: string // ISO date string (YYYY-MM-DD)
  folder_id?: string | null
  position?: number
  external_ref?: string | null
  committed_delivery_date?: string | null
  customer_id?: string | null
  priority?: ProjectPriority
}

export interface ProjectUpdate {
  name?: string
  start_date?: string
  end_date?: string
  /** Send null to take the project out of its folder; omit to leave it unchanged. */
  folder_id?: string | null
  position?: number
  /** Send null to clear the reference; omit to leave it unchanged. */
  external_ref?: string | null
  /** Send null to clear the commitment; omit to leave it unchanged. */
  committed_delivery_date?: string | null
  /** Send null to clear the override and fall back to the folder; omit to leave unchanged. */
  customer_id?: string | null
  priority?: ProjectPriority
}
