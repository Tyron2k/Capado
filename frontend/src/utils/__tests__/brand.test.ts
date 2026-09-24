/**
 * Deriving shades from a brand colour, and the two shades the app shell depends on.
 *
 * The interesting assertions here are not the arithmetic — they are the two CONTRAST properties the
 * shell relies on and would otherwise only discover by eye:
 *
 *   The navigation shade must clear WCAG AA for SMALL text (4.5:1) against white. It exists because the
 *   untouched brand colour does not: the product's own default, #0d9488, gives white 3.74:1. That is
 *   not enough for the small labels the navigation carries.
 *
 *   The header shade must be DARKER than the navigation one, because the whole composition is "header
 *   deeper than nav". Getting that backwards would not throw; it would just look wrong, and only on
 *   screens nobody happened to open.
 */
import { describe, expect, it } from 'vitest'

import { BRAND_SHADE_FACTORS, brandShade, HEADER_SHADE, NAVBAR_SHADE } from '../brand'
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

describe('the shades the app shell paints with', () => {
  it('gives the navigation enough contrast for white text, which the raw brand does not', () => {
    // The measurement that produced NAVBAR_SHADE. If someone sets it back to 0 to get "the exact
    // colour", this fails and says why.
    expect(contrastAgainstWhite(DEFAULT_BRAND)).toBeLessThan(4.5)

    const navBg = brandShade(DEFAULT_BRAND, NAVBAR_SHADE)
    expect(contrastAgainstWhite(navBg)).toBeGreaterThanOrEqual(4.5)
    expect(readableTextForeground(navBg)).toBe('white')
  })

  it('keeps the header darker than the navigation', () => {
    const navBg = brandShade(DEFAULT_BRAND, NAVBAR_SHADE)
    const headerBg = brandShade(DEFAULT_BRAND, HEADER_SHADE)
    expect(luminance(headerBg)).toBeLessThan(luminance(navBg))
    expect(readableTextForeground(headerBg)).toBe('white')
  })

  it('lets both surfaces carry the same foreground', () => {
    // True of the untouched colour as well -- asserted so that a future change to the shades, or to
    // the text-contrast threshold, cannot quietly leave the navigation and the header wearing
    // different text colours.
    const navFg = readableTextForeground(brandShade(DEFAULT_BRAND, NAVBAR_SHADE))
    const headerFg = readableTextForeground(brandShade(DEFAULT_BRAND, HEADER_SHADE))
    expect(navFg).toBe(headerFg)
  })

  it('orders the ten theme shades from lightest to darkest', () => {
    const shades = BRAND_SHADE_FACTORS.map((f) => brandShade(DEFAULT_BRAND, f))
    const luminances = shades.map(luminance)
    for (let i = 1; i < luminances.length; i += 1) {
      expect(luminances[i]).toBeLessThan(luminances[i - 1])
    }
    // Mantine reads index 5 as the configured colour and index 6 as `filled`, which is why the header
    // was already a shade off the brand before any of this.
    expect(shades[5]).toBe(DEFAULT_BRAND)
  })
})
