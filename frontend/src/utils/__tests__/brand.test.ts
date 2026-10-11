import { describe, expect, it } from 'vitest'

import { BRAND_SHADE_FACTORS, brandShade } from '../brand'
import { readableTextForeground } from '../contrast'

/** Relative luminance, per WCAG — duplicated here so the test does not lean on the code it checks. */
function luminance(hex: string): number {
  const channels = [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)))
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
}

function contrastAgainstWhite(hex: string): number {
  return (1 + 0.05) / (luminance(hex) + 0.05)
}

/** The product's default brand colour, and the one the contrast claims above were measured against. */
const DEFAULT_BRAND = '#0d9488'

describe('brandShade', () => {
  it('returns the colour unchanged at factor 0', () => {
    expect(brandShade(DEFAULT_BRAND, 0)).toBe(DEFAULT_BRAND)
  })

  it('mixes toward white for a positive factor and toward black for a negative one', () => {
    expect(brandShade('#808080', 1)).toBe('#ffffff')
    expect(brandShade('#808080', -1)).toBe('#000000')
    expect(luminance(brandShade(DEFAULT_BRAND, 0.5))).toBeGreaterThan(luminance(DEFAULT_BRAND))
    expect(luminance(brandShade(DEFAULT_BRAND, -0.5))).toBeLessThan(luminance(DEFAULT_BRAND))
  })

  it('pads single-digit channels, so the result is always a valid six-digit hex', () => {
    // #0d9488 darkened hard drives the red channel to a single hex digit; without padding the string
    // would be five characters and every downstream colour parse would fail.
    for (const factor of BRAND_SHADE_FACTORS) {
      expect(brandShade(DEFAULT_BRAND, factor)).toMatch(/^#[0-9a-f]{6}$/)
    }
  })

  it('passes malformed input straight through instead of throwing', () => {
    // The brand colour is a settings field somebody types into: a half-finished hex must not take the
    // application down mid-keystroke. Same choice the contrast helpers make.
    expect(brandShade('#0d94', -0.25)).toBe('#0d94')
    expect(brandShade('teal', -0.25)).toBe('teal')
    expect(brandShade('', -0.25)).toBe('')
  })
})

describe('brand palette contrast and ordering', () => {
  it('gives darker accent shades enough contrast for small white text', () => {
    // A palette index carrying small text must be darker than the untouched accent.
    expect(contrastAgainstWhite(DEFAULT_BRAND)).toBeLessThan(4.5)

    const accentBg = brandShade(DEFAULT_BRAND, BRAND_SHADE_FACTORS[7])
    expect(contrastAgainstWhite(accentBg)).toBeGreaterThanOrEqual(4.5)
    expect(readableTextForeground(accentBg)).toBe('white')
  })

  it('orders the deeper accent below the lighter accent', () => {
    const accentBg = brandShade(DEFAULT_BRAND, BRAND_SHADE_FACTORS[7])
    const deeperBg = brandShade(DEFAULT_BRAND, BRAND_SHADE_FACTORS[8])
    expect(luminance(deeperBg)).toBeLessThan(luminance(accentBg))
    expect(readableTextForeground(deeperBg)).toBe('white')
  })

  it('lets adjacent dark accent shades carry the same foreground', () => {
    // Palette or threshold changes must not silently invert text between adjacent accents.
    const accentFg = readableTextForeground(brandShade(DEFAULT_BRAND, BRAND_SHADE_FACTORS[7]))
    const deeperFg = readableTextForeground(brandShade(DEFAULT_BRAND, BRAND_SHADE_FACTORS[8]))
    expect(accentFg).toBe(deeperFg)
  })

  it('orders the ten theme shades from lightest to darkest', () => {
    const shades = BRAND_SHADE_FACTORS.map((f) => brandShade(DEFAULT_BRAND, f))
    const luminances = shades.map(luminance)
    for (let i = 1; i < luminances.length; i += 1) {
      expect(luminances[i]).toBeLessThan(luminances[i - 1])
    }
    // The configured colour stays intact even though filled accent controls use a darker shade.
    expect(shades[5]).toBe(DEFAULT_BRAND)
  })
})
