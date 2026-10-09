import type { ApiBody, ApiResponse } from './contracts'

/**
 * API functions for projects and project folders (CRUD).
 */

import apiClient from './client'
import type { components } from './generated/schema'
import type { Project, ProjectFolder, ProjectFolderDeleteResult } from '../types/project'

const BASE_PATH = '/api/projects'

const FOLDERS_PATH = '/api/project-folders'

/**
 * Fetch projects, optionally restricted to one folder.
 *
 * @param folderId - A folder id to list its projects, `'unfiled'` for projects in no
 *   folder, or undefined for everything. The caller has to say which, because none of
 *   the three is a safe default.
 */
export async function getProjects(
  signal?: AbortSignal,
  folderId?: string | 'unfiled',
): Promise<Project[]> {
  const projects: Project[] = []
  let total: number
  do {
    const { data } = await apiClient.get<ApiResponse<'/api/projects', 'get'>>(BASE_PATH, {
      signal,
      params: { limit: 500, offset: projects.length, ...(folderId ? { folder_id: folderId } : {}) },
    })
    total = data.total
    if (data.items.length === 0 && projects.length < total) {
      throw new Error('The project list ended before all projects were loaded')
    }
    projects.push(...data.items)
  } while (projects.length < total)
  return projects
}

/** Create a new project. */
export async function createProject(data: ApiBody<'/api/projects', 'post'>): Promise<Project> {
  const response = await apiClient.post<ApiResponse<'/api/projects', 'post'>>(BASE_PATH, data)
  return response.data
}

/** Update a project. */
export async function updateProject(
  id: string,
  data: ApiBody<'/api/projects/{project_id}', 'put'>,
): Promise<Project> {
  const response = await apiClient.put<ApiResponse<'/api/projects/{project_id}', 'put'>>(
    `${BASE_PATH}/${id}`,
    data,
  )
  return response.data
}

/** Delete a project. */
export async function deleteProject(id: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/projects/{project_id}', 'delete'>>(`${BASE_PATH}/${id}`)
}

// ---------------------------------------------------------------------------
// Project folders
// ---------------------------------------------------------------------------

/** Fetch every folder. Unpaginated: a tree cannot be rendered one page at a time. */
export async function getProjectFolders(signal?: AbortSignal): Promise<ProjectFolder[]> {
  const response = await apiClient.get<ApiResponse<'/api/project-folders', 'get'>>(FOLDERS_PATH, {
    signal,
  })
  return response.data
}

/** Create a folder, optionally inside another. */
export async function createProjectFolder(
  data: ApiBody<'/api/project-folders', 'post'>,
): Promise<ProjectFolder> {
  const response = await apiClient.post<ApiResponse<'/api/project-folders', 'post'>>(
    FOLDERS_PATH,
    data,
  )
  return response.data
}

/**
 * Rename, move, or reorder a folder.
 *
 * Passing `parent_id: null` moves it to the top level. Omitting the key leaves the
 * parent alone — the backend distinguishes the two by what was actually sent.
 */
export async function updateProjectFolder(
  id: string,
  data: ApiBody<'/api/project-folders/{folder_id}', 'put'>,
): Promise<ProjectFolder> {
  const response = await apiClient.put<ApiResponse<'/api/project-folders/{folder_id}', 'put'>>(
    `${FOLDERS_PATH}/${id}`,
    data,
  )
  return response.data
}

/**
 * Delete a folder. Projects inside are unfiled and sub-folders move up one level;
 * nothing is deleted along with it.
 */
export async function deleteProjectFolder(id: string): Promise<ProjectFolderDeleteResult> {
  const response = await apiClient.delete<
    ApiResponse<'/api/project-folders/{folder_id}', 'delete'>
  >(`${FOLDERS_PATH}/${id}`)
  return response.data
}

// ---------------------------------------------------------------------------
// Schedule analysis
// ---------------------------------------------------------------------------

type ProjectSchedule = components['schemas']['ProjectScheduleResponse']

/** Critical path and float for one project. */
export async function getProjectSchedule(
  projectId: string,
  signal?: AbortSignal,
): Promise<ProjectSchedule> {
  const { data } = await apiClient.get<ApiResponse<'/api/projects/{project_id}/schedule', 'get'>>(
    `${BASE_PATH}/${projectId}/schedule`,
    {
      signal,
    },
  )
  return data
}
