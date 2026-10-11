/** Build the Mantine accent palette from the configured company colour. */

/**
 * Mix a hex colour toward white (positive factor) or black (negative factor).
 *
 * `factor` 0 returns the colour unchanged, 1 returns white, -1 returns black. Values outside [-1, 1]
 * are not rejected but are meaningless; callers pass literals.
 *
 * Invalid input is returned unchanged rather than throwing: the brand colour comes from a settings
 * field the operator types into, and a half-typed hex must not take the application down. The contrast
 * helpers make the same choice for the same reason.
 */
export function brandShade(hex: string, factor: number): string {
  if (!/^#[0-9a-fA-F]{6}$/.test(hex)) return hex

  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)

  const target = factor >= 0 ? 255 : 0
  const amount = Math.abs(factor)
  const mix = (base: number) => Math.round(base + (target - base) * amount)

  const channel = (value: number) => mix(value).toString(16).padStart(2, '0')
  return `#${channel(r)}${channel(g)}${channel(b)}`
}

/**
 * The ten shades Mantine wants, lightest to darkest, with the operator's colour at index 5.
 *
 * Index 5 preserves the configured colour; the theme uses index 7 for filled accent controls
 * in both colour schemes so their foreground contrast remains consistent.
 */
export const BRAND_SHADE_FACTORS = [0.9, 0.75, 0.6, 0.4, 0.2, 0, -0.1, -0.25, -0.4, -0.55] as const
