import type { ApiBody, ApiResponse } from './contracts'

import type { components } from './generated/schema'

/**
 * API client functions for user management (admin only).
 */

import apiClient from './client'

export type User = components['schemas']['UserResponse']

export type UserCreateData = components['schemas']['UserCreateRequest']

export type UserUpdateData = components['schemas']['UserUpdateRequest']

type UsersListResponse = components['schemas']['UserListResponse']

const BASE_PATH = '/api/users'

/** Fetch paginated list of all users (admin only). */
export async function getUsers(skip = 0, limit = 50): Promise<UsersListResponse> {
  const response = await apiClient.get<ApiResponse<'/api/users', 'get'>>(BASE_PATH, {
    params: { skip, limit },
  })
  return response.data
}

/** Create a new user (admin only). */
export async function createUser(data: ApiBody<'/api/users', 'post'>): Promise<User> {
  const response = await apiClient.post<ApiResponse<'/api/users', 'post'>>(BASE_PATH, data)
  return response.data
}

/** Update an existing user (admin only). */
export async function updateUser(
  id: string,
  data: ApiBody<'/api/users/{user_id}', 'put'>,
): Promise<User> {
  const response = await apiClient.put<ApiResponse<'/api/users/{user_id}', 'put'>>(
    `${BASE_PATH}/${id}`,
    data,
  )
  return response.data
}

/** Deactivate a user (soft-delete, admin only). */
export async function deleteUser(id: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/users/{user_id}', 'delete'>>(`${BASE_PATH}/${id}`)
}

/** Permanently delete a user from the database (hard-delete, admin only). */
export async function permanentlyDeleteUser(id: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/users/{user_id}/permanent', 'delete'>>(
    `${BASE_PATH}/${id}/permanent`,
  )
}
