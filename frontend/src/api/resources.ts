/**
 * API functions for resources (personal & infrastructure).
 */

import apiClient from './client'
import type {
  InfrastructureResource,
  InfrastructureResourceCreate,
  InfrastructureResourceUpdate,
  InfrastructureTreeNode,
  PersonalResource,
  PersonalResourceCreate,
  PersonalResourceUpdate,
  PersonalTreeNode,
  ResourceGroup,
} from '../types/resource'

// --- Resource Groups ---

/** Fetch resource groups, optionally filtered by resource type. */
export async function getGroups(
  resourceType?: 'personal' | 'infrastructure',
  signal?: AbortSignal,
): Promise<ResourceGroup[]> {
  const params = resourceType ? { resource_type: resourceType } : undefined
  const response = await apiClient.get<{ items: ResourceGroup[]; total: number }>(
    '/api/resource-groups',
    { params, signal },
  )
  return response.data.items
}

/** Create a new resource group. */
export async function createGroup(data: {
  name: string
  resource_type: 'personal' | 'infrastructure'
  parent_id?: string | null
}): Promise<ResourceGroup> {
  const response = await apiClient.post<ResourceGroup>('/api/resource-groups', data)
  return response.data
}

/** Update an existing resource group. */
export async function updateGroup(
  id: string,
  data: { name?: string; parent_id?: string | null },
): Promise<ResourceGroup> {
  const response = await apiClient.put<ResourceGroup>(`/api/resource-groups/${id}`, data)
  return response.data
}

/** Delete a resource group. */
export async function deleteGroup(id: string): Promise<void> {
  await apiClient.delete(`/api/resource-groups/${id}`)
}

// --- Infrastructure Resources ---

/** Fetch a single infrastructure resource by ID. */
export async function getInfrastructureResource(id: string): Promise<InfrastructureResource> {
  const response = await apiClient.get<InfrastructureResource>(
    `/api/resources/infrastructure/${id}`,
  )
  return response.data
}

/** Create a new infrastructure resource. */
export async function createInfrastructureResource(
  data: InfrastructureResourceCreate,
): Promise<InfrastructureResource> {
  const response = await apiClient.post<InfrastructureResource>(
    '/api/resources/infrastructure',
    data,
  )
  return response.data
}

/** Update an existing infrastructure resource. */
export async function updateInfrastructureResource(
  id: string,
  data: InfrastructureResourceUpdate,
): Promise<InfrastructureResource> {
  const response = await apiClient.put<InfrastructureResource>(
    `/api/resources/infrastructure/${id}`,
    data,
  )
  return response.data
}

/** Delete an infrastructure resource. */
export async function deleteInfrastructureResource(id: string): Promise<void> {
  await apiClient.delete(`/api/resources/infrastructure/${id}`)
}

// --- Personal Resources ---

/** Fetch a single personal resource by ID. */
export async function getPersonalResource(id: string): Promise<PersonalResource> {
  const response = await apiClient.get<PersonalResource>(`/api/resources/personal/${id}`)
  return response.data
}

/** Create a new personal resource. */
export async function createPersonalResource(
  data: PersonalResourceCreate,
): Promise<PersonalResource> {
  const response = await apiClient.post<PersonalResource>('/api/resources/personal', data)
  return response.data
}

/** Update an existing personal resource. */
export async function updatePersonalResource(
  id: string,
  data: PersonalResourceUpdate,
): Promise<PersonalResource> {
  const response = await apiClient.put<PersonalResource>(`/api/resources/personal/${id}`, data)
  return response.data
}

/** Delete a personal resource. */
export async function deletePersonalResource(id: string): Promise<void> {
  await apiClient.delete(`/api/resources/personal/${id}`)
}

// --- Tree Endpoints (Hierarchy) ---

/**
 * Loads the complete personal hierarchy as a tree structure.
 */
export async function getPersonalTree(): Promise<PersonalTreeNode[]> {
  const response = await apiClient.get<PersonalTreeNode[]>('/api/resources/personal/tree')
  return response.data
}

/**
 * Loads the complete infrastructure hierarchy as a tree structure.
 */
export async function getInfrastructureTree(): Promise<InfrastructureTreeNode[]> {
  const response = await apiClient.get<InfrastructureTreeNode[]>(
    '/api/resources/infrastructure/tree',
  )
  return response.data
}
