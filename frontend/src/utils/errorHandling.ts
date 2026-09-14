/**
 * Shared error handling utilities for API call error responses.
 * Provides a standardized way to extract error messages from Axios errors
 * and display them via Mantine notifications.
 */

import axios from 'axios'
import { notifications } from '@mantine/notifications'

/**
 * Extract the error detail message from an Axios error response.
 * Returns the `detail` field from the response body, or the provided fallback.
 */
export function getErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    return error.response?.data?.detail ?? fallback
  }
  return fallback
}

/**
 * Show a standardized error notification for a failed API call.
 * Extracts the message from `response.data.detail` and displays it
 * using Mantine notifications with `color: 'red'` and a translated title.
 */
export function showErrorNotification(
  error: unknown,
  title: string,
  fallbackMessage: string,
): void {
  const message = getErrorMessage(error, fallbackMessage)
  notifications.show({ title, message, color: 'red' })
}
