import { allPages } from './pagination'
import type { ApiBody, ApiResponse } from './contracts'

/**
 * API functions for resources (personal & infrastructure).
 */

import apiClient from './client'
import type {
  InfrastructureResource,
  InfrastructureTreeNode,
  PersonalResource,
  PersonalTreeNode,
  ResourceGroup,
} from '../types/resource'

// --- Resource Groups ---

/** Fetch resource groups, optionally filtered by resource type. */
export async function getGroups(
  resourceType?: 'personal' | 'infrastructure',
  signal?: AbortSignal,
): Promise<ResourceGroup[]> {
  return allPages(async (offset) => {
    const params = resourceType ? { resource_type: resourceType } : undefined
    const response = await apiClient.get<ApiResponse<'/api/resource-groups', 'get'>>(
      '/api/resource-groups',
      { params: { ...params, limit: 500, offset }, signal },
    )
    return response.data
  })
}

/** Create a new resource group. */
export async function createGroup(
  data: ApiBody<'/api/resource-groups', 'post'>,
): Promise<ResourceGroup> {
  const response = await apiClient.post<ApiResponse<'/api/resource-groups', 'post'>>(
    '/api/resource-groups',
    data,
  )
  return response.data
}

/** Update an existing resource group. */
export async function updateGroup(
  id: string,
  data: ApiBody<'/api/resource-groups/{group_id}', 'put'>,
): Promise<ResourceGroup> {
  const response = await apiClient.put<ApiResponse<'/api/resource-groups/{group_id}', 'put'>>(
    `/api/resource-groups/${id}`,
    data,
  )
  return response.data
}

/** Delete a resource group. */
export async function deleteGroup(id: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/resource-groups/{group_id}', 'delete'>>(
    `/api/resource-groups/${id}`,
  )
}

// --- Infrastructure Resources ---

/** Fetch a single infrastructure resource by ID. */
export async function getInfrastructureResource(id: string): Promise<InfrastructureResource> {
  const response = await apiClient.get<
    ApiResponse<'/api/resources/infrastructure/{resource_id}', 'get'>
  >(`/api/resources/infrastructure/${id}`)
  return response.data
}

/** Create a new infrastructure resource. */
export async function createInfrastructureResource(
  data: ApiBody<'/api/resources/infrastructure', 'post'>,
): Promise<InfrastructureResource> {
  const response = await apiClient.post<ApiResponse<'/api/resources/infrastructure', 'post'>>(
    '/api/resources/infrastructure',
    data,
  )
  return response.data
}

/** Update an existing infrastructure resource. */
export async function updateInfrastructureResource(
  id: string,
  data: ApiBody<'/api/resources/infrastructure/{resource_id}', 'put'>,
): Promise<InfrastructureResource> {
  const response = await apiClient.put<
    ApiResponse<'/api/resources/infrastructure/{resource_id}', 'put'>
  >(`/api/resources/infrastructure/${id}`, data)
  return response.data
}

/** Delete an infrastructure resource. */
export async function deleteInfrastructureResource(id: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/resources/infrastructure/{resource_id}', 'delete'>>(
    `/api/resources/infrastructure/${id}`,
  )
}

// --- Personal Resources ---

/** Fetch a single personal resource by ID. */
export async function getPersonalResource(id: string): Promise<PersonalResource> {
  const response = await apiClient.get<ApiResponse<'/api/resources/personal/{resource_id}', 'get'>>(
    `/api/resources/personal/${id}`,
  )
  return response.data
}

/** Create a new personal resource. */
export async function createPersonalResource(
  data: ApiBody<'/api/resources/personal', 'post'>,
): Promise<PersonalResource> {
  const response = await apiClient.post<ApiResponse<'/api/resources/personal', 'post'>>(
    '/api/resources/personal',
    data,
  )
  return response.data
}

/** Update an existing personal resource. */
export async function updatePersonalResource(
  id: string,
  data: ApiBody<'/api/resources/personal/{resource_id}', 'put'>,
): Promise<PersonalResource> {
  const response = await apiClient.put<ApiResponse<'/api/resources/personal/{resource_id}', 'put'>>(
    `/api/resources/personal/${id}`,
    data,
  )
  return response.data
}

/** Delete a personal resource. */
export async function deletePersonalResource(id: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/resources/personal/{resource_id}', 'delete'>>(
    `/api/resources/personal/${id}`,
  )
}

// --- Tree Endpoints (Hierarchy) ---

/**
 * Loads the complete personal hierarchy as a tree structure.
 */
export async function getPersonalTree(signal?: AbortSignal): Promise<PersonalTreeNode[]> {
  const response = await apiClient.get<ApiResponse<'/api/resources/personal/tree', 'get'>>(
    '/api/resources/personal/tree',
    { signal },
  )
  return response.data
}

/**
 * Loads the complete infrastructure hierarchy as a tree structure.
 */
export async function getInfrastructureTree(
  signal?: AbortSignal,
): Promise<InfrastructureTreeNode[]> {
  const response = await apiClient.get<ApiResponse<'/api/resources/infrastructure/tree', 'get'>>(
    '/api/resources/infrastructure/tree',
    { signal },
  )
  return response.data
}
