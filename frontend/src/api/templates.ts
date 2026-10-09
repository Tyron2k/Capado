import { allPages } from './pagination'
import type { ApiBody, ApiResponse } from './contracts'

import type { components } from './generated/schema'

/**
 * API client for work package templates and their skill requirements.
 */

import apiClient from './client'

export type TemplateListItem = components['schemas']['TemplateListResponse']

export type TemplateRequirement = components['schemas']['RequirementResponse']

type TemplateDetail = components['schemas']['TemplateResponse']

/** Fetch all templates (list view). */
export async function getTemplates(): Promise<TemplateListItem[]> {
  return allPages(async (offset) => {
    const response = await apiClient.get<ApiResponse<'/api/templates', 'get'>>('/api/templates', {
      params: { limit: 500, offset },
    })
    return response.data
  })
}

/** Fetch a single template with its requirements. */
export async function getTemplate(id: string): Promise<TemplateDetail> {
  const response = await apiClient.get<ApiResponse<'/api/templates/{template_id}', 'get'>>(
    `/api/templates/${id}`,
  )
  return response.data
}

/** Add a skill requirement to a template. */
export async function addTemplateRequirement(
  templateId: string,
  data: ApiBody<'/api/templates/{template_id}/requirements', 'post'>,
): Promise<TemplateRequirement> {
  const response = await apiClient.post<
    ApiResponse<'/api/templates/{template_id}/requirements', 'post'>
  >(`/api/templates/${templateId}/requirements`, data)
  return response.data
}

/** Remove a skill requirement from a template. */
export async function removeTemplateRequirement(
  templateId: string,
  requirementId: string,
): Promise<void> {
  await apiClient.delete<
    ApiResponse<'/api/templates/{template_id}/requirements/{requirement_id}', 'delete'>
  >(`/api/templates/${templateId}/requirements/${requirementId}`)
}
