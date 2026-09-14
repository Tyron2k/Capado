/**
 * API client for work package templates and their skill requirements.
 */

import apiClient from './client'

export interface TemplateListItem {
  id: string
  name: string
  description: string | null
  requirement_count: number
  created_at: string
}

export interface TemplateRequirement {
  id: string
  skill_id: string
  skill_name: string
  skill_attribute_id: string | null
  skill_attribute_name: string | null
  quantity: number
}

interface TemplateDetail {
  id: string
  name: string
  description: string | null
  requirements: TemplateRequirement[]
  created_at: string
}

/** Fetch all templates (list view). */
export async function getTemplates(): Promise<TemplateListItem[]> {
  const response = await apiClient.get<{ items: TemplateListItem[]; total: number }>(
    '/api/templates',
  )
  return response.data.items
}

/** Fetch a single template with its requirements. */
export async function getTemplate(id: string): Promise<TemplateDetail> {
  const response = await apiClient.get<TemplateDetail>(`/api/templates/${id}`)
  return response.data
}

/** Add a skill requirement to a template. */
export async function addTemplateRequirement(
  templateId: string,
  data: { skill_id: string; skill_attribute_id?: string | null; quantity: number },
): Promise<TemplateRequirement> {
  const response = await apiClient.post<TemplateRequirement>(
    `/api/templates/${templateId}/requirements`,
    data,
  )
  return response.data
}

/** Remove a skill requirement from a template. */
export async function removeTemplateRequirement(
  templateId: string,
  requirementId: string,
): Promise<void> {
  await apiClient.delete(`/api/templates/${templateId}/requirements/${requirementId}`)
}
