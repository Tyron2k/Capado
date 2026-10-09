import type { components } from '../api/generated/schema'

/**
 * TypeScript types for the unified skill system.
 * Based on the backend schemas in app/schemas/skill.py.
 */

// --- Skill ---

export type Skill = components['schemas']['SkillResponse']

export type SkillAttribute = components['schemas']['SkillAttributeResponse']

export type SkillWithAttributes = components['schemas']['SkillWithAttributesResponse']

// --- Resource Skill Assignment ---

export type ResourceSkillAssignment = components['schemas']['ResourceSkillAssignmentResponse']

// --- Search Result ---

export type PersonalResourceSearchResult = components['schemas']['ResourceSearchResult']
