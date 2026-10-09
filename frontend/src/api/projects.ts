/**
 * API functions for projects and project folders (CRUD).
 */

import apiClient from './client'
import type { components, paths } from './generated/schema'
import type {
  Project,
  ProjectCreate,
  ProjectFolder,
  ProjectFolderCreate,
  ProjectFolderDeleteResult,
  ProjectFolderUpdate,
  ProjectUpdate,
} from '../types/project'

const BASE_PATH = '/api/projects'
type ProjectsPage = paths['/api/projects']['get']['responses'][200]['content']['application/json']

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
    const { data } = await apiClient.get<ProjectsPage>(BASE_PATH, {
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
export async function createProject(data: ProjectCreate): Promise<Project> {
  const response = await apiClient.post<Project>(BASE_PATH, data)
  return response.data
}

/** Update a project. */
export async function updateProject(id: string, data: ProjectUpdate): Promise<Project> {
  const response = await apiClient.put<Project>(`${BASE_PATH}/${id}`, data)
  return response.data
}

/** Delete a project. */
export async function deleteProject(id: string): Promise<void> {
  await apiClient.delete(`${BASE_PATH}/${id}`)
}

// ---------------------------------------------------------------------------
// Project folders
// ---------------------------------------------------------------------------

/** Fetch every folder. Unpaginated: a tree cannot be rendered one page at a time. */
export async function getProjectFolders(signal?: AbortSignal): Promise<ProjectFolder[]> {
  const response = await apiClient.get<ProjectFolder[]>(FOLDERS_PATH, { signal })
  return response.data
}

/** Create a folder, optionally inside another. */
export async function createProjectFolder(data: ProjectFolderCreate): Promise<ProjectFolder> {
  const response = await apiClient.post<ProjectFolder>(FOLDERS_PATH, data)
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
  data: ProjectFolderUpdate,
): Promise<ProjectFolder> {
  const response = await apiClient.put<ProjectFolder>(`${FOLDERS_PATH}/${id}`, data)
  return response.data
}

/**
 * Delete a folder. Projects inside are unfiled and sub-folders move up one level;
 * nothing is deleted along with it.
 */
export async function deleteProjectFolder(id: string): Promise<ProjectFolderDeleteResult> {
  const response = await apiClient.delete<ProjectFolderDeleteResult>(`${FOLDERS_PATH}/${id}`)
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
  const { data } = await apiClient.get<ProjectSchedule>(`${BASE_PATH}/${projectId}/schedule`, {
    signal,
  })
  return data
}
