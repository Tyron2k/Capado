/**
 * API client for the unified skill system (skills, attributes, assignments, search).
 */

import apiClient from './client'
import type {
  Skill,
  SkillAttribute,
  SkillWithAttributes,
  ResourceSkillAssignment,
  PersonalResourceSearchResult,
} from '../types/skill'

/** Response shape for paginated skills with attributes. */
interface SkillsWithAttributesResponse {
  items: SkillWithAttributes[]
  total: number
  limit: number
  offset: number
}

// --- Skills ---

/** Fetch all skills with their attributes (paginated, returns all by default). */
export async function getSkillsWithAttributes(
  resourceType?: string,
): Promise<SkillWithAttributes[]> {
  const params: Record<string, string | number> = { limit: 500 }
  if (resourceType) params.resource_type = resourceType
  const response = await apiClient.get<SkillsWithAttributesResponse>(
    '/api/skills/with-attributes',
    { params },
  )
  return response.data.items
}

/** Create a new skill. */
export async function createSkill(data: { name: string; resource_type?: string }): Promise<Skill> {
  const response = await apiClient.post<Skill>('/api/skills', data)
  return response.data
}

/** Update an existing skill. */
export async function updateSkill(id: string, data: { name: string }): Promise<Skill> {
  const response = await apiClient.put<Skill>(`/api/skills/${id}`, data)
  return response.data
}

/** Delete a skill. */
export async function deleteSkill(id: string): Promise<void> {
  await apiClient.delete(`/api/skills/${id}`)
}

// --- Skill Attributes ---

/** Create a new attribute for a skill. */
export async function createSkillAttribute(
  skillId: string,
  data: { name: string },
): Promise<SkillAttribute> {
  const response = await apiClient.post<SkillAttribute>(`/api/skills/${skillId}/attributes`, data)
  return response.data
}

/** Update an existing skill attribute. */
export async function updateSkillAttribute(
  attributeId: string,
  data: { name: string },
): Promise<SkillAttribute> {
  const response = await apiClient.put<SkillAttribute>(
    `/api/skills/attributes/${attributeId}`,
    data,
  )
  return response.data
}

/** Delete a skill attribute. */
export async function deleteSkillAttribute(attributeId: string): Promise<void> {
  await apiClient.delete(`/api/skills/attributes/${attributeId}`)
}

// --- Personal Resource Skills ---

/** Fetch skill assignments for a personal resource. */
export async function getPersonalResourceSkills(
  resourceId: string,
): Promise<ResourceSkillAssignment[]> {
  const response = await apiClient.get<ResourceSkillAssignment[]>(
    `/api/personal-resources/${resourceId}/skills`,
  )
  return response.data
}

/** Assign a skill attribute to a personal resource. */
/** Optional bounds sent when a qualification is added. */
interface QualificationBounds {
  valid_from?: string | null
  valid_until?: string | null
  level?: number | null
}

export async function addPersonalResourceSkill(
  resourceId: string,
  data: { skill_attribute_id: string } & QualificationBounds,
): Promise<ResourceSkillAssignment> {
  const response = await apiClient.post<ResourceSkillAssignment>(
    `/api/personal-resources/${resourceId}/skills`,
    data,
  )
  return response.data
}

/** Remove a skill assignment from a personal resource. */
export async function removePersonalResourceSkill(
  resourceId: string,
  assignmentId: string,
): Promise<void> {
  await apiClient.delete(`/api/personal-resources/${resourceId}/skills/${assignmentId}`)
}

// --- Infrastructure Resource Skills ---

/** Fetch skill assignments for an infrastructure resource. */
export async function getInfrastructureResourceSkills(
  resourceId: string,
): Promise<ResourceSkillAssignment[]> {
  const response = await apiClient.get<ResourceSkillAssignment[]>(
    `/api/infrastructure-resources/${resourceId}/skills`,
  )
  return response.data
}

/** Assign a skill attribute to an infrastructure resource. */
export async function addInfrastructureResourceSkill(
  resourceId: string,
  data: { skill_attribute_id: string } & QualificationBounds,
): Promise<ResourceSkillAssignment> {
  const response = await apiClient.post<ResourceSkillAssignment>(
    `/api/infrastructure-resources/${resourceId}/skills`,
    data,
  )
  return response.data
}

/** Remove a skill assignment from an infrastructure resource. */
export async function removeInfrastructureResourceSkill(
  resourceId: string,
  assignmentId: string,
): Promise<void> {
  await apiClient.delete(`/api/infrastructure-resources/${resourceId}/skills/${assignmentId}`)
}

// --- Resource Search ---

/** Search personal resources by skill qualification. */
export async function searchByQualification(params: {
  skill_id?: string
  skill_attribute_id?: string
}): Promise<PersonalResourceSearchResult[]> {
  const response = await apiClient.get<PersonalResourceSearchResult[]>(
    '/api/personal-resources/search',
    { params },
  )
  return response.data
}

/**
 * Change the bounds of a qualification the resource already holds.
 *
 * Only the fields present in `data` are changed; sending an explicit `null` clears one.
 * That distinction is why this is a PATCH and not a re-add: without it an expiry date
 * could never be removed once entered.
 */
export async function updatePersonalResourceSkill(
  resourceId: string,
  assignmentId: string,
  data: QualificationBounds,
): Promise<ResourceSkillAssignment> {
  const response = await apiClient.patch<ResourceSkillAssignment>(
    `/api/personal-resources/${resourceId}/skills/${assignmentId}`,
    data,
  )
  return response.data
}

export async function updateInfrastructureResourceSkill(
  resourceId: string,
  assignmentId: string,
  data: QualificationBounds,
): Promise<ResourceSkillAssignment> {
  const response = await apiClient.patch<ResourceSkillAssignment>(
    `/api/infrastructure-resources/${resourceId}/skills/${assignmentId}`,
    data,
  )
  return response.data
}
