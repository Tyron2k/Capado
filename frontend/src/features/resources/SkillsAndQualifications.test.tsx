/**
 * SKILLS ARE THE ONE PIECE OF MASTER DATA THAT REACHES INTO THE PLAN.
 *
 * Every other boundary in this migration divides cleanly: a customer or a folder is a label, an
 * assignment or a date is a commitment. A skill is neither and both. It is edited as master data, but a
 * work-package requirement points at it and a person's qualification points at it, and whether the
 * assignment between them is sound is decided by comparing those two THROUGH the catalogue. Delete an
 * attribute and no assignment changes — yet a covered requirement becomes uncovered, which is a
 * conflict and a digest finding.
 *
 * So a skill write invalidates the digest where a customer write does not, and that asymmetry is what
 * the first test pins.
 *
 * The second test pins something else the migration FIXED rather than moved: the matrix's optimistic
 * rollback was wrong under concurrency. The snapshot was captured from React state at click time, so
 * ticking two boxes quickly meant the second click's snapshot already contained the first's unconfirmed
 * row. If the FIRST request then failed, its rollback discarded the second — a change the user had made
 * and seen accepted. Ticking fast is the normal way to use this screen, so it was reachable.
 */
import { MantineProvider } from '@mantine/core'
import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

// Both the catalogue and the per-resource qualifications live in api/skills. importOriginal because
// the module also exports pure helpers.
vi.mock('../../api/skills', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/skills')>()),
  getSkillsWithAttributes: vi.fn(),
  createSkill: vi.fn(),
  updateSkill: vi.fn(),
  deleteSkill: vi.fn(),
  createSkillAttribute: vi.fn(),
  updateSkillAttribute: vi.fn(),
  deleteSkillAttribute: vi.fn(),
  getPersonalResourceSkills: vi.fn(),
  addPersonalResourceSkill: vi.fn(),
  removePersonalResourceSkill: vi.fn(),
  updatePersonalResourceSkill: vi.fn(),
}))

const showErrorNotification = vi.fn()
vi.mock('../../utils/errorHandling', () => ({
  showErrorNotification: (...args: unknown[]) => showErrorNotification(...args),
}))

vi.mock('@mantine/notifications', () => ({ notifications: { show: vi.fn() } }))

import {
  addPersonalResourceSkill,
  deleteSkill,
  getPersonalResourceSkills,
  getSkillsWithAttributes,
  removePersonalResourceSkill,
} from '../../api/skills'
import { queryKeys } from '../../api/queryClient'
import { createTestQueryClient, trackInvalidations } from '../../testUtils/queryClient'
import { I18nProvider } from '../../i18n'
import { SkillsPanel } from './panels/SkillsPanel'
import { SkillMatrix } from './SkillMatrix'

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  window.confirm = vi.fn(() => true)
})

const catalogue = [
  {
    id: 's1',
    name: 'Schweißen',
    resource_type: 'personal',
    attributes: [
      { id: 'a1', name: 'zertifiziert', skill_id: 's1' },
      { id: 'a2', name: 'Aluminium', skill_id: 's1' },
    ],
  },
]

function renderWith(ui: React.ReactElement) {
  const client = createTestQueryClient()
  const invalidated = trackInvalidations(client)
  const view = render(
    <QueryClientProvider client={client}>
      <MantineProvider>
        <I18nProvider locale="de">{ui}</I18nProvider>
      </MantineProvider>
    </QueryClientProvider>,
  )
  return { ...view, invalidated, client }
}

beforeEach(() => {
  vi.mocked(getSkillsWithAttributes).mockResolvedValue(catalogue as never)
  vi.mocked(getPersonalResourceSkills).mockResolvedValue([])
  showErrorNotification.mockReset()
})

describe('the skill catalogue reaches into the plan', () => {
  it('invalidates the digest, because deleting a skill can uncover a requirement', async () => {
    vi.mocked(deleteSkill).mockResolvedValue(undefined as never)

    const { invalidated } = renderWith(<SkillsPanel resourceType="personal" />)
    await waitFor(() => expect(screen.getByTestId('skill-delete-s1')).toBeTruthy())

    fireEvent.click(screen.getByTestId('skill-delete-s1'))
    await waitFor(() => expect(deleteSkill).toHaveBeenCalledWith('s1'))

    await waitFor(() => {
      for (const key of [
        queryKeys.skills.all,
        queryKeys.resources.all,
        queryKeys.projects.all,
        queryKeys.conflicts.all,
        // The point of the batch: a name in a catalogue changes what the digest reports.
        queryKeys.digest.all,
      ]) {
        expect(invalidated).toContainEqual([...key])
      }
    })

    // The assignments are untouched -- what changed is whether they are correct, which is what
    // conflicts and digest are for.
    expect(invalidated).not.toContainEqual([...queryKeys.assignments.all])
    expect(invalidated).not.toContainEqual([...queryKeys.capacity.all])
  })

  it('invalidates nothing when the skill delete fails', async () => {
    vi.mocked(deleteSkill).mockRejectedValue(new Error('boom'))

    const { invalidated } = renderWith(<SkillsPanel resourceType="personal" />)
    await waitFor(() => expect(screen.getByTestId('skill-delete-s1')).toBeTruthy())
    fireEvent.click(screen.getByTestId('skill-delete-s1'))

    await waitFor(() => expect(showErrorNotification).toHaveBeenCalledTimes(1))
    expect(invalidated).toEqual([])
  })
})

describe('optimistic qualification toggles under concurrency', () => {
  it('converges on the server truth when one of two concurrent toggles fails', async () => {
    // a1 is slow and FAILS, a2 is fast and SUCCEEDS. What is asserted is the END STATE: a2 held, a1
    // not. That holds however the rollback snapshot was taken, which is the point -- the invalidation,
    // not the rollback, is what makes the outcome correct.
    //
    // The mock keeps SERVER STATE, because the invalidation that follows each settle refetches: a test
    // whose refetch answers with an empty list would be asserting against a server that forgot the
    // write, not against the rollback.
    const server: { skill_attribute_id: string; id: string }[] = []
    vi.mocked(getPersonalResourceSkills).mockImplementation(() =>
      Promise.resolve(
        server.map((row) => ({
          ...row,
          skill_id: 's1',
          skill_name: 'Schweißen',
          attribute_name: row.skill_attribute_id === 'a1' ? 'zertifiziert' : 'Aluminium',
          valid_from: null,
          valid_until: null,
          level: null,
        })) as never,
      ),
    )

    let failFirst: (reason: Error) => void = () => {}
    vi.mocked(addPersonalResourceSkill).mockImplementation((_resourceId: string, body: unknown) => {
      const attrId = (body as { skill_attribute_id: string }).skill_attribute_id
      if (attrId === 'a1') {
        return new Promise((_resolve, reject) => {
          failFirst = reject
        }) as never
      }
      server.push({ skill_attribute_id: 'a2', id: 'real-a2' })
      return Promise.resolve({
        id: 'real-a2',
        skill_attribute_id: 'a2',
        skill_id: 's1',
        skill_name: 'Schweißen',
        attribute_name: 'Aluminium',
        valid_from: null,
        valid_until: null,
        level: null,
      } as never)
    })

    const { client } = renderWith(<SkillMatrix resourceId="r1" resourceType="personal" />)
    await waitFor(() => expect(screen.getByTestId('qualification-a1')).toBeTruthy())

    fireEvent.click(screen.getByTestId('qualification-a1'))
    fireEvent.click(screen.getByTestId('qualification-a2'))

    // a2 lands.
    await waitFor(() =>
      expect(
        client
          .getQueryData<{ skill_attribute_id: string }[]>(queryKeys.resources.qualifications('r1'))
          ?.some((a) => a.skill_attribute_id === 'a2'),
      ).toBe(true),
    )

    failFirst(new Error('rejected'))
    await waitFor(() => expect(showErrorNotification).toHaveBeenCalledTimes(1))

    // a2 survives and a1 does not. The rollback alone would not guarantee this; the refetch does.
    await waitFor(() => {
      const after = client.getQueryData<{ skill_attribute_id: string }[]>(
        queryKeys.resources.qualifications('r1'),
      )
      expect(after?.some((a) => a.skill_attribute_id === 'a2')).toBe(true)
      expect(after?.some((a) => a.skill_attribute_id === 'a1')).toBe(false)
    })
  })

  it('shows the toggled qualification immediately, before the request resolves', async () => {
    let resolveAdd: (value: unknown) => void = () => {}
    vi.mocked(addPersonalResourceSkill).mockImplementation(
      () => new Promise((resolve) => (resolveAdd = resolve)) as never,
    )

    const { client } = renderWith(<SkillMatrix resourceId="r1" resourceType="personal" />)
    await waitFor(() => expect(screen.getByTestId('qualification-a1')).toBeTruthy())

    fireEvent.click(screen.getByTestId('qualification-a1'))

    // Optimism is the point of this screen: a foreman ticks a row of boxes, and a spinner per box
    // would make that unusable.
    await waitFor(() =>
      expect(
        client
          .getQueryData<{ skill_attribute_id: string }[]>(queryKeys.resources.qualifications('r1'))
          ?.some((a) => a.skill_attribute_id === 'a1'),
      ).toBe(true),
    )

    resolveAdd({
      id: 'real-a1',
      skill_attribute_id: 'a1',
      skill_id: 's1',
      skill_name: 'Schweißen',
      attribute_name: 'zertifiziert',
      valid_from: null,
      valid_until: null,
      level: null,
    })
    await waitFor(() => expect(removePersonalResourceSkill).not.toHaveBeenCalled())
  })
})
