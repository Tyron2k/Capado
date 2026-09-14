/**
 * Customers.
 *
 * Replaces a free-text field where "Acme" and "Acme GmbH" were two customers and nothing could say
 * they were one. Uniqueness is enforced case-insensitively in the database, so a duplicate comes
 * back as a 409 naming the collision — offer the existing one rather than a variant spelling.
 */

import apiClient from './client'

export interface Customer {
  id: string
  name: string
  reference: string
  note: string
  is_active: boolean
  /** Folders naming this customer. Everything inside them inherits it. */
  folder_count: number
  /** Projects naming it directly, folders aside. */
  project_count: number
}

export async function getCustomers(includeInactive = false): Promise<Customer[]> {
  const response = await apiClient.get<Customer[]>('/api/customers', {
    params: includeInactive ? { include_inactive: true } : undefined,
  })
  return response.data
}

export async function createCustomer(data: {
  name: string
  reference?: string
  note?: string
}): Promise<Customer> {
  const response = await apiClient.post<Customer>('/api/customers', data)
  return response.data
}

export async function updateCustomer(
  id: string,
  data: { name?: string; reference?: string; note?: string; is_active?: boolean },
): Promise<Customer> {
  const response = await apiClient.patch<Customer>(`/api/customers/${id}`, data)
  return response.data
}

export async function deleteCustomer(id: string): Promise<void> {
  await apiClient.delete(`/api/customers/${id}`)
}
