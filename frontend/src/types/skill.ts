/**
 * TypeScript types for the unified skill system.
 * Based on the backend schemas in app/schemas/skill.py.
 */

// --- Skill ---

export interface Skill {
  id: string
  name: string
  resource_type: string
}

export interface SkillAttribute {
  id: string
  skill_id: string
  name: string
}

export interface SkillWithAttributes {
  id: string
  name: string
  resource_type: string
  attributes: SkillAttribute[]
}

// --- Resource Skill Assignment ---

export interface ResourceSkillAssignment {
  id: string
  skill_attribute_id: string
  skill_id: string
  skill_name: string
  attribute_name: string
  valid_from: string | null
  /**
   * Last day the qualification counts, or null when it does not expire.
   *
   * Validity is checked against the WORK, not against today: a certificate expiring in
   * March does not cover a job planned for April.
   */
  valid_until: string | null
  /** Assessed proficiency 1-5, or null when nobody assessed it — not the same as 1. */
  level: number | null
}

// --- Search Result ---

export interface PersonalResourceSearchResult {
  id: string
  name: string
  department: string
  skills: ResourceSkillAssignment[]
}
