// @vitest-environment jsdom

import { beforeAll, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { createTestQueryClient } from '../../testUtils/queryClient'
import { I18nProvider } from '../../i18n'
import { ProblemCard, type ProblemBucket } from './ProblemCard'

vi.mock('./ConflictAssignmentList', () => ({ ConflictAssignmentList: () => null }))
vi.mock('./ConflictSuggestions', () => ({ ConflictSuggestions: () => null }))

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  })
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

const bucket: ProblemBucket = {
  type: 'capacity',
  resource_id: 'anna',
  resource_name: 'Anna Berger',
  resource_type: 'personal',
  assignments: [],
  conflicts: [],
}

describe('focused problem card', () => {
  it('opens the matching resource immediately', () => {
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <MantineProvider env="test">
          <I18nProvider locale="de">
            <ProblemCard bucket={bucket} onChanged={vi.fn()} initiallyOpen />
          </I18nProvider>
        </MantineProvider>
      </QueryClientProvider>,
    )

    expect(screen.getByText('Anna Berger').closest('button')).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })
})
