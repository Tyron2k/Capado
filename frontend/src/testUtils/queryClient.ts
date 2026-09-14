/**
 * A query client for tests, and the reasons its defaults differ from production's.
 *
 * Every converted screen needs a `QueryClientProvider` in its test, so this exists before the third
 * one gets written. Two hand-rolled copies were already in the tree; a third and fourth would be the
 * duplication that lets two test files disagree about what "a query client" means.
 *
 * A FRESH CLIENT PER TEST, never a shared one. A shared client carries the previous test's cached rows
 * into the next, and the failure surfaces as an order-dependent flake rather than as the leak it is.
 * That is also why the production client is created inside a `useState` initialiser rather than at
 * module scope.
 */

import { QueryClient } from '@tanstack/react-query'

/**
 * Retries off, nothing stale.
 *
 * `retry: false` because production's single retry would make every rejection test wait for a second
 * attempt before reporting — a test that takes a second longer to assert the same thing, and a timeout
 * when someone lowers the waitFor budget.
 *
 * `staleTime: 0` because a test that wants to observe a refetch should not have to reason about a
 * 30-second window. The production value is a decision about how people use a planning tool; it says
 * nothing useful inside a single render.
 *
 * `mutations: { retry: false }` for the same reason on the write side.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  })
}

/**
 * Record which keys a client was asked to invalidate, while still invalidating them.
 *
 * For asserting what a mutation declared untrue. The assertion that matters is not "the list
 * refreshed" — that passes whether or not the OTHER screens' keys were included — but which keys were
 * named. Wrapping rather than replacing keeps the real invalidation running, so the test also proves
 * the call was well-formed.
 */
export function trackInvalidations(client: QueryClient): unknown[][] {
  const seen: unknown[][] = []
  const original = client.invalidateQueries.bind(client)
  client.invalidateQueries = ((filters?: Parameters<QueryClient['invalidateQueries']>[0]) => {
    seen.push((filters?.queryKey ?? []) as unknown[])
    return original(filters)
  }) as QueryClient['invalidateQueries']
  return seen
}
