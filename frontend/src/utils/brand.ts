/**
 * Deriving shades from the operator's brand colour.
 *
 * This lived inside App.tsx as a local `hexToShades`, which was fine while the Mantine theme was the
 * only consumer. It is shared now because the app shell needs two SPECIFIC shades as hex — not as CSS
 * variables — so it can ask `readableForeground` which text colour each of those two surfaces can
 * carry. A CSS variable cannot answer that question; only the value can.
 *
 * Duplicating the mixing arithmetic in two files was the alternative, and it is the kind of thing that
 * drifts silently: the theme and the shell would tint by slightly different amounts and nobody would
 * know which was intended.
 */

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
 * Index 5 being the untouched colour is what lets the shell use "the chosen colour, exactly" for one
 * surface and a darker step for another. Mantine's own `filled` default is index 6, which is why the
 * header was very slightly darker than the configured brand even before any of this.
 */
export const BRAND_SHADE_FACTORS = [0.9, 0.75, 0.6, 0.4, 0.2, 0, -0.1, -0.25, -0.4, -0.55] as const

/**
 * The shade the app shell paints the navigation with — one step darker than the configured colour.
 *
 * NOT THE COLOUR UNTOUCHED, and the reason is a threshold difference rather than a foreground flip.
 * `readableForeground` uses 3.0:1, which is the WCAG AA figure for LARGE text and UI components. The
 * navigation's labels are small text, where AA asks for 4.5:1. The product's default #0d9488 gives white
 * only 3.74:1 — enough to satisfy the helper, not enough for the labels it is being asked about. At -0.25
 * the same colour gives 6.04:1, and the header at -0.4 gives 8.20:1.
 *
 * Both shades resolve to white text, and so does the untouched colour: the helper was never going to pick
 * a dark foreground here. The shade exists to make white text actually legible rather than merely
 * permitted.
 *
 * The operator's colour is still the colour; it is one step deeper on the same hue, which is already true
 * of the header — Mantine's `filled` index is 6, never the raw value.
 */
export const NAVBAR_SHADE = -0.25

/**
 * The shade the app shell paints the header with — three steps darker than the navigation.
 *
 * DARKER RATHER THAN LIGHTER, and that is a structural choice rather than a taste one. A light header
 * beside a saturated navigation only reads as one composition while the navigation is wide enough to
 * anchor it; collapse the navigation to icons and the coloured block shrinks to a stub with a pale band
 * running off it. A darker header is a full-width band whose relationship to the navigation does not
 * depend on the navigation's width, so it survives the collapse unchanged — and it needs no separate
 * treatment in dark mode, because both surfaces stay in the same hue rather than one of them turning
 * into a bright stripe.
 */
export const HEADER_SHADE = -0.4
