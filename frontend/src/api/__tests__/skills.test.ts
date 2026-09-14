/**
 * THE SKILLS API SURFACE: paths, verbs and payload shapes.
 *
 * These wrappers are one line each, which is exactly why they were untested and exactly why a mistake in
 * one is expensive: a wrong path or a wrong verb produces a 404 or a silent no-op at runtime, and nothing
 * in TypeScript can catch either — the URL is a string and every wrapper returns the same shape.
 *
 * Two decisions here are load-bearing rather than incidental, and both are pinned:
 *
 *   The bounds update is a PATCH, not a re-add. Only the fields present are changed, so an explicit
 *   `null` CLEARS one. Without that distinction an expiry date could never be removed once entered —
 *   which is what makes a renewed certificate expressible.
 *
 *   `getSkillsWithAttributes` omits `resource_type` entirely when no type is given, rather than sending
 *   an empty one. The catalogue answers differently for "all types" than for a named type, and the query
 *   layer files those under different keys on that basis (see `skills.withAttributes`).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

import apiClient from '../client'
import {
  addInfrastructureResourceSkill,
  addPersonalResourceSkill,
  createSkill,
  createSkillAttribute,
  deleteSkill,
  deleteSkillAttribute,
  getInfrastructureResourceSkills,
  getPersonalResourceSkills,
  getSkillsWithAttributes,
  removeInfrastructureResourceSkill,
  removePersonalResourceSkill,
  searchByQualification,
  updateInfrastructureResourceSkill,
  updatePersonalResourceSkill,
  updateSkill,
  updateSkillAttribute,
} from '../skills'

const mocked = vi.mocked(apiClient)

beforeEach(() => {
  vi.clearAllMocks()
  mocked.get.mockResolvedValue({ data: { items: [] } } as never)
  mocked.post.mockResolvedValue({ data: {} } as never)
  mocked.put.mockResolvedValue({ data: {} } as never)
  mocked.patch.mockResolvedValue({ data: {} } as never)
  mocked.delete.mockResolvedValue({ data: undefined } as never)
})

describe('the skill catalogue', () => {
  it('asks for a generous page and unwraps the items', async () => {
    mocked.get.mockResolvedValue({ data: { items: [{ id: 's1' }] } } as never)

    const result = await getSkillsWithAttributes()

    expect(mocked.get).toHaveBeenCalledWith('/api/skills/with-attributes', {
      params: { limit: 500 },
    })
    // A catalogue is not paged in the UI: the picker shows all of it, so the wrapper unwraps `items`
    // and the caller never sees the envelope.
    expect(result).toEqual([{ id: 's1' }])
  })

  it('OMITS the resource type when none is given, rather than sending an empty one', async () => {
    await getSkillsWithAttributes()
    expect(mocked.get).toHaveBeenCalledWith('/api/skills/with-attributes', {
      params: { limit: 500 },
    })
  })

  it('sends the resource type when one is given', async () => {
    await getSkillsWithAttributes('personal')
    expect(mocked.get).toHaveBeenCalledWith('/api/skills/with-attributes', {
      params: { limit: 500, resource_type: 'personal' },
    })
  })

  it('creates, renames and deletes a skill', async () => {
    await createSkill({ name: 'Schweißen', resource_type: 'personal' })
    expect(mocked.post).toHaveBeenCalledWith('/api/skills', {
      name: 'Schweißen',
      resource_type: 'personal',
    })

    await updateSkill('s1', { name: 'Schweißen (neu)' })
    expect(mocked.put).toHaveBeenCalledWith('/api/skills/s1', { name: 'Schweißen (neu)' })

    await deleteSkill('s1')
    expect(mocked.delete).toHaveBeenCalledWith('/api/skills/s1')
  })

  it('nests an attribute under its skill on create, but addresses it directly afterwards', async () => {
    await createSkillAttribute('s1', { name: 'zertifiziert' })
    expect(mocked.post).toHaveBeenCalledWith('/api/skills/s1/attributes', { name: 'zertifiziert' })

    // An attribute id is unique on its own, so the update and delete routes do NOT repeat the skill.
    // Sending the nested form here would 404.
    await updateSkillAttribute('a1', { name: 'geprüft' })
    expect(mocked.put).toHaveBeenCalledWith('/api/skills/attributes/a1', { name: 'geprüft' })

    await deleteSkillAttribute('a1')
    expect(mocked.delete).toHaveBeenCalledWith('/api/skills/attributes/a1')
  })
})

describe('qualifications held by a resource', () => {
  it('addresses personal and infrastructure resources on separate routes', async () => {
    mocked.get.mockResolvedValue({ data: [] } as never)

    await getPersonalResourceSkills('r1')
    expect(mocked.get).toHaveBeenCalledWith('/api/personal-resources/r1/skills')

    await getInfrastructureResourceSkills('i1')
    expect(mocked.get).toHaveBeenCalledWith('/api/infrastructure-resources/i1/skills')
  })

  it('adds and removes a personal qualification', async () => {
    await addPersonalResourceSkill('r1', { skill_attribute_id: 'a1' })
    expect(mocked.post).toHaveBeenCalledWith('/api/personal-resources/r1/skills', {
      skill_attribute_id: 'a1',
    })

    await removePersonalResourceSkill('r1', 'as1')
    expect(mocked.delete).toHaveBeenCalledWith('/api/personal-resources/r1/skills/as1')
  })

  it('adds and removes an infrastructure qualification', async () => {
    await addInfrastructureResourceSkill('i1', { skill_attribute_id: 'a1' })
    expect(mocked.post).toHaveBeenCalledWith('/api/infrastructure-resources/i1/skills', {
      skill_attribute_id: 'a1',
    })

    await removeInfrastructureResourceSkill('i1', 'as1')
    expect(mocked.delete).toHaveBeenCalledWith('/api/infrastructure-resources/i1/skills/as1')
  })

  it('changes bounds with PATCH, so an explicit null CLEARS a field', async () => {
    // The whole reason this is not a re-add: a re-add cannot express "remove the expiry date", and a
    // renewed certificate is an ordinary event.
    await updatePersonalResourceSkill('r1', 'as1', { valid_until: null })
    expect(mocked.patch).toHaveBeenCalledWith('/api/personal-resources/r1/skills/as1', {
      valid_until: null,
    })

    await updateInfrastructureResourceSkill('i1', 'as1', { level: 3 })
    expect(mocked.patch).toHaveBeenCalledWith('/api/infrastructure-resources/i1/skills/as1', {
      level: 3,
    })
  })

  it('sends only the fields it was given, so an absent field means "leave alone"', async () => {
    await updatePersonalResourceSkill('r1', 'as1', { level: 2 })
    const [, payload] = mocked.patch.mock.calls[0]
    expect(payload).toEqual({ level: 2 })
    expect(payload).not.toHaveProperty('valid_until')
  })
})

describe('searching by qualification', () => {
  it('passes the filter through as query parameters', async () => {
    mocked.get.mockResolvedValue({ data: [] } as never)

    await searchByQualification({ skill_id: 's1', skill_attribute_id: 'a1' })

    expect(mocked.get).toHaveBeenCalledWith('/api/personal-resources/search', {
      params: { skill_id: 's1', skill_attribute_id: 'a1' },
    })
  })

  it('accepts an empty filter, which asks for everybody', async () => {
    mocked.get.mockResolvedValue({ data: [] } as never)

    await searchByQualification({})

    expect(mocked.get).toHaveBeenCalledWith('/api/personal-resources/search', { params: {} })
  })
})
