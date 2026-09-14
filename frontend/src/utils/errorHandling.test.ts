/**
 * Unit tests for error handling utilities.
 *
 * Verifies:
 * - getErrorMessage extracts detail from Axios errors
 * - getErrorMessage returns fallback for non-Axios errors
 * - showErrorNotification calls notifications.show with correct params
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock @mantine/notifications
vi.mock('@mantine/notifications', () => ({
  notifications: {
    show: vi.fn(),
  },
}))

// Mock axios to control isAxiosError
vi.mock('axios', () => ({
  default: {
    isAxiosError: vi.fn(),
  },
  isAxiosError: vi.fn(),
}))

import { notifications } from '@mantine/notifications'
import axios from 'axios'
import { getErrorMessage, showErrorNotification } from './errorHandling'

const mockedIsAxiosError = vi.mocked(axios.isAxiosError)

describe('errorHandling utilities', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('getErrorMessage', () => {
    it('extracts detail from an Axios error response', () => {
      const axiosError = {
        isAxiosError: true,
        response: {
          data: { detail: 'Resource not found' },
        },
      }

      mockedIsAxiosError.mockReturnValue(true)

      const result = getErrorMessage(axiosError, 'Fallback message')
      expect(result).toBe('Resource not found')
    })

    it('returns fallback for non-Axios errors', () => {
      mockedIsAxiosError.mockReturnValue(false)

      const result = getErrorMessage(new Error('generic'), 'Something went wrong')
      expect(result).toBe('Something went wrong')
    })

    it('returns fallback when Axios error has no detail field', () => {
      const axiosError = {
        isAxiosError: true,
        response: {
          data: {},
        },
      }

      mockedIsAxiosError.mockReturnValue(true)

      const result = getErrorMessage(axiosError, 'Server error')
      expect(result).toBe('Server error')
    })

    it('returns fallback when Axios error has no response', () => {
      const axiosError = {
        isAxiosError: true,
        response: undefined,
      }

      mockedIsAxiosError.mockReturnValue(true)

      const result = getErrorMessage(axiosError, 'Network error')
      expect(result).toBe('Network error')
    })
  })

  describe('showErrorNotification', () => {
    it('calls notifications.show with red color and extracted message', () => {
      const axiosError = {
        isAxiosError: true,
        response: {
          data: { detail: 'Conflict detected' },
        },
      }

      mockedIsAxiosError.mockReturnValue(true)

      showErrorNotification(axiosError, 'Error', 'Unknown error')

      expect(notifications.show).toHaveBeenCalledWith({
        title: 'Error',
        message: 'Conflict detected',
        color: 'red',
      })
    })

    it('uses fallback message for non-Axios errors', () => {
      mockedIsAxiosError.mockReturnValue(false)

      showErrorNotification(new Error('oops'), 'Error', 'Something failed')

      expect(notifications.show).toHaveBeenCalledWith({
        title: 'Error',
        message: 'Something failed',
        color: 'red',
      })
    })
  })
})
