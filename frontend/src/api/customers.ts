import type { ApiBody, ApiResponse } from './contracts'

import type { components } from './generated/schema'

/**
 * Customers.
 *
 * Replaces a free-text field where "Acme" and "Acme GmbH" were two customers and nothing could say
 * they were one. Uniqueness is enforced case-insensitively in the database, so a duplicate comes
 * back as a 409 naming the collision — offer the existing one rather than a variant spelling.
 */

import apiClient from './client'

export type Customer = components['schemas']['CustomerResponse']

export async function getCustomers(includeInactive = false): Promise<Customer[]> {
  const response = await apiClient.get<ApiResponse<'/api/customers', 'get'>>('/api/customers', {
    params: includeInactive ? { include_inactive: true } : undefined,
  })
  return response.data
}

export async function createCustomer(data: ApiBody<'/api/customers', 'post'>): Promise<Customer> {
  const response = await apiClient.post<ApiResponse<'/api/customers', 'post'>>(
    '/api/customers',
    data,
  )
  return response.data
}

export async function updateCustomer(
  id: string,
  data: ApiBody<'/api/customers/{customer_id}', 'patch'>,
): Promise<Customer> {
  const response = await apiClient.patch<ApiResponse<'/api/customers/{customer_id}', 'patch'>>(
    `/api/customers/${id}`,
    data,
  )
  return response.data
}

export async function deleteCustomer(id: string): Promise<void> {
  await apiClient.delete<ApiResponse<'/api/customers/{customer_id}', 'delete'>>(
    `/api/customers/${id}`,
  )
}
