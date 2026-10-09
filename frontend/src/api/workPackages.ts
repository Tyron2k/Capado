import type { ApiBody, ApiResponse } from './contracts'

/**
 * API functions for work packages (CRUD) and their skill requirements.
 * Work package CRUD is nested under projects: /api/projects/{projectId}/work-packages
 * Requirements are managed directly: /api/work-packages/{wpId}/requirements
 */

import apiClient from './client'
import type { components, paths } from './generated/schema'
import type {
  WorkPackage,
  WorkPackageCreate,
  WorkPackageDependencies,
  WorkPackageDependency,
  WorkPackageRequirement,
  WorkPackageUpdate,
  WorkPackageWithWarnings,
} from '../types/workPackage'

type WorkPackagesListResponse =
  paths['/api/projects/{project_id}/work-packages']['get']['responses'][200]['content']['application/json']

function basePath(projectId: string): string {
  return `/api/projects/${projectId}/work-packages`
}

/** Fetch all work packages of a project (paginated, returns all by default). */
export async function getWorkPackages(projectId: string): Promise<WorkPackage[]> {
  const packages: WorkPackage[] = []
  let total: number
  do {
    const { data } = await apiClient.get<WorkPackagesListResponse>(basePath(projectId), {
      params: { limit: 500, offset: packages.length },
    })
    total = data.total
    if (data.items.length === 0 && packages.length < total) {
      throw new Error('The work-package list ended before all work packages were loaded')
    }
    packages.push(...data.items)
  } while (packages.length < total)
  return packages
}

/** Create a new work package (returns warnings). */
export async function createWorkPackage(
  projectId: string,
  data: WorkPackageCreate,
): Promise<WorkPackageWithWarnings> {
  const response = await apiClient.post<WorkPackageWithWarnings>(basePath(projectId), data)
  return response.data
}

/** Update a work package (returns warnings). */
export async function updateWorkPackage(
  projectId: string,
  wpId: string,
  data: WorkPackageUpdate,
): Promise<WorkPackageWithWarnings> {
  const response = await apiClient.put<WorkPackageWithWarnings>(
    `${basePath(projectId)}/${wpId}`,
    data,
  )
  return response.data
}

/** Delete a work package (cascades assignments). */
export async function deleteWorkPackage(projectId: string, wpId: string): Promise<void> {
  await apiClient.delete(`${basePath(projectId)}/${wpId}`)
}

// --- Work Package Requirements ---

/** Fetch all skill requirements for a work package. */
export async function getWorkPackageRequirements(wpId: string): Promise<WorkPackageRequirement[]> {
  const response = await apiClient.get<
    ApiResponse<'/api/work-packages/{wp_id}/requirements', 'get'>
  >(`/api/work-packages/${wpId}/requirements`)
  return response.data
}

/** Add a skill requirement to a work package. */
export async function addWorkPackageRequirement(
  wpId: string,
  data: ApiBody<'/api/work-packages/{wp_id}/requirements', 'post'>,
): Promise<WorkPackageRequirement> {
  const response = await apiClient.post<
    ApiResponse<'/api/work-packages/{wp_id}/requirements', 'post'>
  >(`/api/work-packages/${wpId}/requirements`, data)
  return response.data
}

/** Remove a skill requirement from a work package. */
export async function removeWorkPackageRequirement(wpId: string, reqId: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/work-packages/{wp_id}/requirements/{req_id}', 'delete'>>(
    `/api/work-packages/${wpId}/requirements/${reqId}`,
  )
}

/** Copy all requirements from a template to a work package. */
export async function copyRequirementsFromTemplate(
  wpId: string,
  templateId: string,
): Promise<WorkPackageRequirement[]> {
  const response = await apiClient.post<
    ApiResponse<'/api/work-packages/{wp_id}/copy-from-template/{template_id}', 'post'>
  >(`/api/work-packages/${wpId}/copy-from-template/${templateId}`)
  return response.data
}

// ---------------------------------------------------------------------------
// Dependencies
// ---------------------------------------------------------------------------

/** Links in both directions for one work package. */
export async function getWorkPackageDependencies(
  projectId: string,
  wpId: string,
): Promise<WorkPackageDependencies> {
  const { data } = await apiClient.get<
    ApiResponse<'/api/projects/{project_id}/work-packages/{work_package_id}/dependencies', 'get'>
  >(`/api/projects/${projectId}/work-packages/${wpId}/dependencies`)
  return data
}

/**
 * Record that another work package must finish before this one starts.
 *
 * The backend refuses a link that would close a cycle. Dates that merely contradict the
 * link are accepted and surfaced as a warning.
 */
export async function createWorkPackageDependency(
  projectId: string,
  wpId: string,
  predecessorId: string,
  lagWorkingDays = 0,
): Promise<WorkPackageDependency> {
  const { data } = await apiClient.post<
    ApiResponse<'/api/projects/{project_id}/work-packages/{work_package_id}/dependencies', 'post'>
  >(`/api/projects/${projectId}/work-packages/${wpId}/dependencies`, {
    predecessor_id: predecessorId,
    lag_working_days: lagWorkingDays,
  } satisfies components['schemas']['WorkPackageDependencyCreate'] satisfies ApiBody<
    '/api/projects/{project_id}/work-packages/{work_package_id}/dependencies',
    'post'
  >)
  return data
}

/** Change the waiting time on an existing link. */
export async function updateWorkPackageDependencyLag(
  projectId: string,
  wpId: string,
  dependencyId: string,
  lagWorkingDays: number,
): Promise<WorkPackageDependency> {
  const { data } = await apiClient.put<
    ApiResponse<
      '/api/projects/{project_id}/work-packages/{work_package_id}/dependencies/{dependency_id}',
      'put'
    >
  >(`/api/projects/${projectId}/work-packages/${wpId}/dependencies/${dependencyId}`, {
    lag_working_days: lagWorkingDays,
  } satisfies components['schemas']['WorkPackageDependencyUpdate'] satisfies ApiBody<
    '/api/projects/{project_id}/work-packages/{work_package_id}/dependencies/{dependency_id}',
    'put'
  >)
  return data
}

/** Remove a link. Neither work package is touched. */
export async function deleteWorkPackageDependency(
  projectId: string,
  wpId: string,
  dependencyId: string,
): Promise<void> {
  await apiClient.delete<
    ApiResponse<
      '/api/projects/{project_id}/work-packages/{work_package_id}/dependencies/{dependency_id}',
      'delete'
    >
  >(`/api/projects/${projectId}/work-packages/${wpId}/dependencies/${dependencyId}`)
}
