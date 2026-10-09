import { allPages } from './pagination'
import type { ApiBody, ApiQuery, ApiResponse } from './contracts'

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

// --- Skills ---

/** Fetch all skills with their attributes (paginated, returns all by default). */
export async function getSkillsWithAttributes(
  resourceType?: ApiQuery<'/api/skills/with-attributes', 'get'>['resource_type'],
): Promise<SkillWithAttributes[]> {
  return allPages(async (offset) => {
    const params: ApiQuery<'/api/skills/with-attributes', 'get'> = { limit: 500, offset }
    if (resourceType) params.resource_type = resourceType
    const response = await apiClient.get<ApiResponse<'/api/skills/with-attributes', 'get'>>(
      '/api/skills/with-attributes',
      { params },
    )
    return response.data
  })
}

/** Create a new skill. */
export async function createSkill(data: ApiBody<'/api/skills', 'post'>): Promise<Skill> {
  const response = await apiClient.post<ApiResponse<'/api/skills', 'post'>>('/api/skills', data)
  return response.data
}

/** Update an existing skill. */
export async function updateSkill(
  id: string,
  data: ApiBody<'/api/skills/{skill_id}', 'put'>,
): Promise<Skill> {
  const response = await apiClient.put<ApiResponse<'/api/skills/{skill_id}', 'put'>>(
    `/api/skills/${id}`,
    data,
  )
  return response.data
}

/** Delete a skill. */
export async function deleteSkill(id: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/skills/{skill_id}', 'delete'>>(`/api/skills/${id}`)
}

// --- Skill Attributes ---

/** Create a new attribute for a skill. */
export async function createSkillAttribute(
  skillId: string,
  data: ApiBody<'/api/skills/{skill_id}/attributes', 'post'>,
): Promise<SkillAttribute> {
  const response = await apiClient.post<ApiResponse<'/api/skills/{skill_id}/attributes', 'post'>>(
    `/api/skills/${skillId}/attributes`,
    data,
  )
  return response.data
}

/** Update an existing skill attribute. */
export async function updateSkillAttribute(
  attributeId: string,
  data: ApiBody<'/api/skills/attributes/{attribute_id}', 'put'>,
): Promise<SkillAttribute> {
  const response = await apiClient.put<ApiResponse<'/api/skills/attributes/{attribute_id}', 'put'>>(
    `/api/skills/attributes/${attributeId}`,
    data,
  )
  return response.data
}

/** Delete a skill attribute. */
export async function deleteSkillAttribute(attributeId: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/skills/attributes/{attribute_id}', 'delete'>>(
    `/api/skills/attributes/${attributeId}`,
  )
}

// --- Personal Resource Skills ---

/** Fetch skill assignments for a personal resource. */
export async function getPersonalResourceSkills(
  resourceId: string,
): Promise<ResourceSkillAssignment[]> {
  const response = await apiClient.get<
    ApiResponse<'/api/personal-resources/{resource_id}/skills', 'get'>
  >(`/api/personal-resources/${resourceId}/skills`)
  return response.data
}

/** Assign a skill attribute to a personal resource. */
/** Optional bounds sent when a qualification is added. */

export async function addPersonalResourceSkill(
  resourceId: string,
  data: ApiBody<'/api/personal-resources/{resource_id}/skills', 'post'>,
): Promise<ResourceSkillAssignment> {
  const response = await apiClient.post<
    ApiResponse<'/api/personal-resources/{resource_id}/skills', 'post'>
  >(`/api/personal-resources/${resourceId}/skills`, data)
  return response.data
}

/** Remove a skill assignment from a personal resource. */
export async function removePersonalResourceSkill(
  resourceId: string,
  assignmentId: string,
): Promise<void> {
  await apiClient.delete<
    ApiResponse<'/api/personal-resources/{resource_id}/skills/{assignment_id}', 'delete'>
  >(`/api/personal-resources/${resourceId}/skills/${assignmentId}`)
}

// --- Infrastructure Resource Skills ---

/** Fetch skill assignments for an infrastructure resource. */
export async function getInfrastructureResourceSkills(
  resourceId: string,
): Promise<ResourceSkillAssignment[]> {
  const response = await apiClient.get<
    ApiResponse<'/api/infrastructure-resources/{resource_id}/skills', 'get'>
  >(`/api/infrastructure-resources/${resourceId}/skills`)
  return response.data
}

/** Assign a skill attribute to an infrastructure resource. */
export async function addInfrastructureResourceSkill(
  resourceId: string,
  data: ApiBody<'/api/infrastructure-resources/{resource_id}/skills', 'post'>,
): Promise<ResourceSkillAssignment> {
  const response = await apiClient.post<
    ApiResponse<'/api/infrastructure-resources/{resource_id}/skills', 'post'>
  >(`/api/infrastructure-resources/${resourceId}/skills`, data)
  return response.data
}

/** Remove a skill assignment from an infrastructure resource. */
export async function removeInfrastructureResourceSkill(
  resourceId: string,
  assignmentId: string,
): Promise<void> {
  await apiClient.delete<
    ApiResponse<'/api/infrastructure-resources/{resource_id}/skills/{assignment_id}', 'delete'>
  >(`/api/infrastructure-resources/${resourceId}/skills/${assignmentId}`)
}

// --- Resource Search ---

/** Search personal resources by skill qualification. */
export async function searchByQualification(
  params: ApiQuery<'/api/personal-resources/search', 'get'>,
): Promise<PersonalResourceSearchResult[]> {
  const response = await apiClient.get<ApiResponse<'/api/personal-resources/search', 'get'>>(
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
  data: ApiBody<'/api/personal-resources/{resource_id}/skills/{assignment_id}', 'patch'>,
): Promise<ResourceSkillAssignment> {
  const response = await apiClient.patch<
    ApiResponse<'/api/personal-resources/{resource_id}/skills/{assignment_id}', 'patch'>
  >(`/api/personal-resources/${resourceId}/skills/${assignmentId}`, data)
  return response.data
}

export async function updateInfrastructureResourceSkill(
  resourceId: string,
  assignmentId: string,
  data: ApiBody<'/api/infrastructure-resources/{resource_id}/skills/{assignment_id}', 'patch'>,
): Promise<ResourceSkillAssignment> {
  const response = await apiClient.patch<
    ApiResponse<'/api/infrastructure-resources/{resource_id}/skills/{assignment_id}', 'patch'>
  >(`/api/infrastructure-resources/${resourceId}/skills/${assignmentId}`, data)
  return response.data
}
