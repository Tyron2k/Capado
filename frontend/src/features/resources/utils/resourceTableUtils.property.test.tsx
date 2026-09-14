/**
 * Property-Based Test: Group header row correctness
 *
 * Feature: unified-page-layout
 * Property 2: Group header row correctness
 *
 * Validates: Requirements 2.3, 2.4, 2.5
 *
 * For any generated flat resource array (0–50 resources, 1–10 unique group
 * names, random names), the `buildGroupedRows` function SHALL:
 * 1. Produce exactly N GroupHeaderRow elements for N distinct groups
 * 2. Each header's count equals the number of resources with that group_name
 * 3. Total row count equals N headers + total resources
 * 4. Resources within each group appear after their header and before the next header
 */
import { describe, expect, it } from 'vitest'
import * as fc from 'fast-check'
import { isValidElement, type ReactElement } from 'react'

import { buildGroupedRows } from './resourceTableUtils'

// --- Types ---

interface TestResource {
  id: string
  name: string
  group_name?: string
}

// --- Generators ---

/** Generates 1–10 unique group names. */
const groupNamesArb: fc.Arbitrary<string[]> = fc
  .array(fc.string({ minLength: 1, maxLength: 20 }), { minLength: 1, maxLength: 10 })
  .map((names) => [...new Set(names)])
  .filter((names) => names.length >= 1)

/**
 * Generates a flat resource array that may include resources with undefined group_name.
 * This tests the fallback to '—' in buildGroupedRows.
 */
const resourceArrayWithUndefinedGroupArb: fc.Arbitrary<TestResource[]> = groupNamesArb.chain(
  (groupNames) =>
    fc.array(
      fc.record({
        id: fc.uuid(),
        name: fc.string({ minLength: 1, maxLength: 30 }),
        group_name: fc.option(fc.constantFrom(...groupNames), { nil: undefined }),
      }),
      { minLength: 0, maxLength: 50 },
    ),
)

// --- Helpers ---

/** Marker type for mock resource rows returned by renderRow. */
const RESOURCE_ROW_TYPE = 'resource-row'

/** Mock renderRow that returns a tagged React element identifying the resource. */
function mockRenderRow(resource: TestResource): ReactElement {
  return <div data-type={RESOURCE_ROW_TYPE} data-id={resource.id} key={resource.id} />
}

/** Checks if a ReactNode is a GroupHeaderRow element (rendered by Table.Tr with group-header testid). */
function isGroupHeader(node: unknown): node is ReactElement {
  if (!isValidElement(node)) return false
  const props = node.props as Record<string, unknown>
  const testId = props['data-testid']
  return typeof testId === 'string' && testId.startsWith('group-header-')
}

/** Checks if a ReactNode is a mock resource row. */
function isResourceRow(node: unknown): node is ReactElement {
  if (!isValidElement(node)) return false
  const props = node.props as Record<string, unknown>
  return props['data-type'] === RESOURCE_ROW_TYPE
}

/** Extracts the group name from a GroupHeaderRow element's data-testid. */
function getHeaderGroupName(node: ReactElement): string {
  const props = node.props as Record<string, unknown>
  const testId = props['data-testid'] as string
  return testId.replace('group-header-', '')
}

/** Extracts the resource id from a mock resource row element. */
function getResourceId(node: ReactElement): string {
  const props = node.props as Record<string, unknown>
  return props['data-id'] as string
}

// --- Property Tests ---

describe('Feature: unified-page-layout, Property 2: Group header row correctness', () => {
  it('produces exactly N GroupHeaderRow elements for N distinct groups', () => {
    fc.assert(
      fc.property(resourceArrayWithUndefinedGroupArb, (resources) => {
        const rows = buildGroupedRows(resources, 5, mockRenderRow)

        // Count distinct groups (undefined maps to '—')
        const distinctGroups = new Set(resources.map((r) => r.group_name ?? '—'))
        // If resources is empty, there are no groups
        const expectedHeaderCount = resources.length === 0 ? 0 : distinctGroups.size

        const headers = rows.filter(isGroupHeader)
        expect(headers.length).toBe(expectedHeaderCount)
      }),
      { numRuns: 100 },
    )
  })

  it("each header's count equals the number of resources with that group_name", () => {
    fc.assert(
      fc.property(resourceArrayWithUndefinedGroupArb, (resources) => {
        const rows = buildGroupedRows(resources, 5, mockRenderRow)
        const headers = rows.filter(isGroupHeader)

        for (const header of headers) {
          const groupName = getHeaderGroupName(header as ReactElement)
          // Count resources in this group
          const expectedCount = resources.filter((r) => (r.group_name ?? '—') === groupName).length

          // GroupHeaderRow renders Table.Tr > Table.Td with children as a React array:
          // [groupName, ' (', count, ')']
          // Extract the count by inspecting the Table.Td children.
          const trProps = (header as ReactElement).props as Record<string, unknown>
          const tdElement = trProps['children'] as ReactElement
          const tdProps = tdElement.props as Record<string, unknown>
          const tdChildren = tdProps['children'] as unknown[]

          // Children is an array: [groupName, ' (', count, ')']
          // The count is the third element (index 2)
          const displayedCount = Array.isArray(tdChildren) ? tdChildren[2] : null
          expect(displayedCount).toBe(expectedCount)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('total row count equals N headers + total resources', () => {
    fc.assert(
      fc.property(resourceArrayWithUndefinedGroupArb, (resources) => {
        const rows = buildGroupedRows(resources, 5, mockRenderRow)

        const distinctGroups = new Set(resources.map((r) => r.group_name ?? '—'))
        const expectedHeaderCount = resources.length === 0 ? 0 : distinctGroups.size
        const expectedTotal = expectedHeaderCount + resources.length

        expect(rows.length).toBe(expectedTotal)
      }),
      { numRuns: 100 },
    )
  })

  it('resources within each group appear after their header and before the next header', () => {
    fc.assert(
      fc.property(resourceArrayWithUndefinedGroupArb, (resources) => {
        if (resources.length === 0) return // trivially true for empty input

        const rows = buildGroupedRows(resources, 5, mockRenderRow)

        // Walk through rows and verify ordering
        let currentGroupName: string | null = null
        const resourcesSeenPerGroup = new Map<string, string[]>()

        for (const row of rows) {
          if (isGroupHeader(row)) {
            currentGroupName = getHeaderGroupName(row as ReactElement)
            if (!resourcesSeenPerGroup.has(currentGroupName)) {
              resourcesSeenPerGroup.set(currentGroupName, [])
            }
          } else if (isResourceRow(row)) {
            // A resource row must appear after a header
            expect(currentGroupName).not.toBeNull()

            // Find the resource to verify it belongs to the current group
            const resourceId = getResourceId(row as ReactElement)
            const resource = resources.find((r) => r.id === resourceId)
            expect(resource).toBeDefined()

            const resourceGroup = resource!.group_name ?? '—'
            expect(resourceGroup).toBe(currentGroupName)

            resourcesSeenPerGroup.get(currentGroupName!)!.push(resourceId)
          }
        }

        // Verify all resources were accounted for
        const totalSeen = [...resourcesSeenPerGroup.values()].reduce(
          (sum, ids) => sum + ids.length,
          0,
        )
        expect(totalSeen).toBe(resources.length)
      }),
      { numRuns: 100 },
    )
  })
})
