/**
 * API client functions for the initial application setup.
 * Used only when no users exist in the database yet.
 */

import axios from 'axios'
import { API_BASE_URL } from './config'
import type { LoginResponse } from './auth'

const setupClient = axios.create({
  baseURL: API_BASE_URL,
  // Receive the httpOnly refresh-token cookie set by the setup endpoint.
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

interface SetupStatusResponse {
  required: boolean
}

interface SetupData {
  name: string
  email: string
  password: string
}

/** Check whether initial setup is required (no users exist). */
export async function getSetupStatus(): Promise<SetupStatusResponse> {
  const response = await setupClient.get<SetupStatusResponse>('auth/setup-status')
  return response.data
}

/** Create the first admin user. Returns login tokens on success. */
export async function postSetup(data: SetupData): Promise<LoginResponse> {
  const response = await setupClient.post<LoginResponse>('auth/setup', data)
  return response.data
}
