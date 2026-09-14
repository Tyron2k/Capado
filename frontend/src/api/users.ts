/**
 * API client functions for user management (admin only).
 */

import apiClient from './client'

export interface User {
  id: string
  email: string
  name: string
  role: 'admin' | 'editor' | 'viewer'
  scope_group_ids: string[] | null
  scope_project_ids: string[] | null
  is_active: boolean
  must_change_password: boolean
  /** The scheduled person this account belongs to, or null when nobody linked it. */
  resource_id: string | null
  created_at: string
  updated_at: string
}

export interface UserCreateData {
  name: string
  email: string
  password: string
  role: 'admin' | 'editor' | 'viewer'
  scope_group_ids?: string[]
  scope_project_ids?: string[]
}

export interface UserUpdateData {
  name?: string
  role?: 'admin' | 'editor' | 'viewer'
  scope_group_ids?: string[] | null
  scope_project_ids?: string[] | null
  /**
   * Reset the password. Only send this when a new one was actually entered: the backend forces a
   * change at next login, so an accidental empty value would lock the account behind a credential
   * nobody knows.
   */
  password?: string
  /** Link the account to the scheduled person it belongs to. Omit to leave an existing link alone. */
  resource_id?: string
  /** Remove the link. Separate from resource_id, because omission has to mean "leave alone". */
  clear_resource_id?: boolean
}

interface UsersListResponse {
  items: User[]
  total: number
}

const BASE_PATH = '/api/users'

/** Fetch paginated list of all users (admin only). */
export async function getUsers(skip = 0, limit = 50): Promise<UsersListResponse> {
  const response = await apiClient.get<UsersListResponse>(BASE_PATH, {
    params: { skip, limit },
  })
  return response.data
}

/** Create a new user (admin only). */
export async function createUser(data: UserCreateData): Promise<User> {
  const response = await apiClient.post<User>(BASE_PATH, data)
  return response.data
}

/** Update an existing user (admin only). */
export async function updateUser(id: string, data: UserUpdateData): Promise<User> {
  const response = await apiClient.put<User>(`${BASE_PATH}/${id}`, data)
  return response.data
}

/** Deactivate a user (soft-delete, admin only). */
export async function deleteUser(id: string): Promise<void> {
  await apiClient.delete(`${BASE_PATH}/${id}`)
}

/** Permanently delete a user from the database (hard-delete, admin only). */
export async function permanentlyDeleteUser(id: string): Promise<void> {
  await apiClient.delete(`${BASE_PATH}/${id}/permanent`)
}
