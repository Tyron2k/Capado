/**
 * Tests for the header's foreground decision.
 *
 * These are written around the colours that caused the bug, not around round numbers: the header
 * painted white unconditionally, so the cases worth pinning are the ordinary corporate brand colours
 * on which white is unreadable — yellow, light green, beige.
 */
import { describe, expect, it } from 'vitest'

import {
  contrastRatio,
  isHexColor,
  readableForeground,
  readableTextForeground,
  relativeLuminance,
} from './contrast'

describe('relativeLuminance', () => {
  it('anchors at black and white', () => {
    expect(relativeLuminance('#000000')).toBe(0)
    expect(relativeLuminance('#ffffff')).toBe(1)
  })

  it('weights green far above blue', () => {
    // The whole reason this is not an average of the channels. Pure green is more than eight times
    // as luminous as pure blue, and an average would call them equal — which is exactly how a
    // saturated blue gets treated as "bright" and a yellow as "medium".
    const green = relativeLuminance('#00ff00')
    const blue = relativeLuminance('#0000ff')
    expect(green).toBeGreaterThan(blue * 8)
  })
})

describe('contrastRatio', () => {
  it('reaches 21 for black on white and 1 for a colour on itself', () => {
    expect(contrastRatio(0, 1)).toBeCloseTo(21, 5)
    const mid = relativeLuminance('#777777')
    expect(contrastRatio(mid, mid)).toBe(1)
  })

  it('is symmetric', () => {
    const a = relativeLuminance('#1c7ed6')
    const b = relativeLuminance('#ffffff')
    expect(contrastRatio(a, b)).toBe(contrastRatio(b, a))
  })
})

describe('readableForeground', () => {
  it('keeps white on the dark brand colours the product ships with', () => {
    expect(readableForeground('#1c7ed6')).toBe('white') // Mantine blue 6, the default
    expect(readableForeground('#2f9e44')).toBe('white') // green
    expect(readableForeground('#000000')).toBe('white')
  })

  it('switches to dark on the light brand colours that broke the header', () => {
    // Each of these is an ordinary corporate colour, and each produced an unreadable header while
    // the foreground was hard-coded white.
    expect(readableForeground('#ffd43b')).not.toBe('white') // yellow
    expect(readableForeground('#8ce99a')).not.toBe('white') // light green
    expect(readableForeground('#f5e6c8')).not.toBe('white') // beige
    expect(readableForeground('#ffffff')).not.toBe('white')
  })

  it('picks whichever foreground measures better, with no gap between the two', () => {
    // Property rather than example: the answer must follow the threshold, and the threshold must be
    // the only thing that decides it.
    const samples = ['#000000', '#333333', '#767676', '#777777', '#888888', '#cccccc', '#ffffff']
    for (const hex of samples) {
      const white = contrastRatio(relativeLuminance(hex), relativeLuminance('#ffffff'))
      const expected = white >= 3.0 ? 'white' : '#1a1b1e'
      expect(readableForeground(hex)).toBe(expected)
    }
  })

  it('keeps white on a mid green even though dark would measure better', () => {
    // The case that decided the design. #2f9e44 gives white 3.45 and dark 5.00, so a
    // maximise-contrast rule would flip an existing legible header to dark text on the next page
    // load. This function prevents unreadable headers; it does not redesign readable ones.
    const brand = relativeLuminance('#2f9e44')
    const white = contrastRatio(brand, relativeLuminance('#ffffff'))
    const dark = contrastRatio(brand, relativeLuminance('#1a1b1e'))

    expect(dark).toBeGreaterThan(white)
    expect(white).toBeGreaterThan(3.0)
    expect(readableForeground('#2f9e44')).toBe('white')
  })

  it('answers white for a Mantine palette name rather than guessing', () => {
    // Not a fallback: a name is resolved by the theme to its shade 6, dark enough for white by
    // Mantine's own design. Inventing a luminance from the string would be worse than assuming.
    expect(readableForeground('blue')).toBe('white')
    expect(readableForeground('grape')).toBe('white')
    expect(readableForeground('')).toBe('white')
  })

  it('treats a malformed hex as a name rather than reading garbage out of it', () => {
    // parseInt('zz', 16) is NaN, and NaN comparisons are false — so an unguarded version would
    // silently pick the dark foreground for a typo.
    expect(isHexColor('#12345')).toBe(false)
    expect(isHexColor('#zzzzzz')).toBe(false)
    expect(readableForeground('#zzzzzz')).toBe('white')
    expect(readableForeground('#12345')).toBe('white')
  })
})

describe('readableTextForeground', () => {
  it('keeps the existing white foreground on the default brand surfaces', () => {
    expect(readableTextForeground('#085952')).toBe('white')
    expect(readableTextForeground('#0a6f66')).toBe('white')
  })

  it('uses black when both white and near-black miss normal-text AA', () => {
    expect(readableTextForeground('#808080')).toBe('#000000')
  })

  it('meets 4.5:1 across dark, mid, and pale brand colours', () => {
    const backgrounds = [
      '#000000',
      '#0d9488',
      '#2f9e44',
      '#66cdaa',
      '#808080',
      '#b3d9c5',
      '#ffffff',
    ]
    for (const background of backgrounds) {
      const foreground = readableTextForeground(background)
      expect(
        contrastRatio(
          relativeLuminance(background),
          relativeLuminance(foreground === 'white' ? '#ffffff' : foreground),
        ),
      ).toBeGreaterThanOrEqual(4.5)
    }
  })
})
