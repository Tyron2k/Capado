/**
 * Tests for assignment utility functions: warning parsing and grouping.
 */
import { describe, it, expect } from 'vitest'
import { formatWarning, groupByProjectAndWorkPackage } from '../assignmentUtils'

describe('formatWarning', () => {
  const mockT = (key: string, params?: Record<string, string | number>) => {
    if (key === 'planning.capacityExceededSingle') {
      return `Capacity exceeded on ${params?.date} (utilization: ${params?.maxUtil}%).`
    }
    if (key === 'planning.capacityExceededMulti') {
      return `Capacity exceeded on ${params?.days} days (${params?.from} to ${params?.to}, max utilization: ${params?.maxUtil}%).`
    }
    return key
  }

  it('parses single-day capacity_exceeded warning', () => {
    const warning = 'capacity_exceeded|days=1|from=2027-01-15|to=2027-01-15|max_util=150'
    const result = formatWarning(warning, mockT)
    expect(result).toContain('Capacity exceeded')
    expect(result).toContain('150')
  })

  it('parses multi-day capacity_exceeded warning', () => {
    const warning = 'capacity_exceeded|days=45|from=2027-01-15|to=2027-02-28|max_util=200'
    const result = formatWarning(warning, mockT)
    expect(result).toContain('45 days')
    expect(result).toContain('200')
  })

  it('returns raw string for unknown warning format', () => {
    const warning = 'Some unknown warning text'
    const result = formatWarning(warning, mockT)
    expect(result).toBe('Some unknown warning text')
  })

  it('handles missing params gracefully', () => {
    const warning = 'capacity_exceeded|days=1'
    const result = formatWarning(warning, mockT)
    expect(result).toContain('Capacity exceeded')
  })
})

describe('groupByProjectAndWorkPackage', () => {
  const assignments = [
    {
      id: '1',
      resource_id: 'r1',
      resource_name: 'Alice',
      resource_type: 'personal' as const,
      work_package_id: 'wp1',
      work_package_name: 'Design',
      project_id: 'p1',
      project_name: 'Project Alpha',
      start_date: '2027-01-01',
      end_date: '2027-01-31',
      allocation_percent: 100,
      start_at: null,
      end_at: null,
      skill_mismatch: false,
      created_at: '2027-01-01',
      updated_at: '2027-01-01',
    },
    {
      id: '2',
      resource_id: 'r2',
      resource_name: 'Bob',
      resource_type: 'personal' as const,
      work_package_id: 'wp1',
      work_package_name: 'Design',
      project_id: 'p1',
      project_name: 'Project Alpha',
      start_date: '2027-01-01',
      end_date: '2027-01-31',
      allocation_percent: 50,
      start_at: null,
      end_at: null,
      skill_mismatch: false,
      created_at: '2027-01-01',
      updated_at: '2027-01-01',
    },
    {
      id: '3',
      resource_id: 'r3',
      resource_name: 'Charlie',
      resource_type: 'personal' as const,
      work_package_id: 'wp2',
      work_package_name: 'Build',
      project_id: 'p2',
      project_name: 'Project Beta',
      start_date: '2027-02-01',
      end_date: '2027-02-28',
      allocation_percent: 75,
      start_at: null,
      end_at: null,
      skill_mismatch: true,
      created_at: '2027-02-01',
      updated_at: '2027-02-01',
    },
  ]

  it('groups assignments by project', () => {
    const result = groupByProjectAndWorkPackage(assignments)
    expect(result).toHaveLength(2)
    expect(result[0].project_name).toBe('Project Alpha')
    expect(result[1].project_name).toBe('Project Beta')
  })

  it('groups work packages within a project', () => {
    const result = groupByProjectAndWorkPackage(assignments)
    const alpha = result.find((p) => p.project_name === 'Project Alpha')!
    expect(alpha.workPackages).toHaveLength(1)
    expect(alpha.workPackages[0].wp_name).toBe('Design')
    expect(alpha.workPackages[0].assignments).toHaveLength(2)
  })

  it('returns empty array for empty input', () => {
    expect(groupByProjectAndWorkPackage([])).toEqual([])
  })

  it('handles assignments without project', () => {
    const noProject = [
      {
        ...assignments[0],
        id: '99',
        project_id: null,
        project_name: null,
      },
    ]
    const result = groupByProjectAndWorkPackage(noProject)
    expect(result).toHaveLength(1)
    expect(result[0].project_name).toBe('—')
  })
})
