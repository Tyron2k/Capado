/**
 * Which foreground colour is readable on the operator's brand colour.
 *
 * WHY THIS EXISTS. `organization_settings.primary_color` is a settings field, explicitly there to be
 * changed by whoever runs the installation, and `hexToShades` in App.tsx accepts any hex it is given.
 * The application header then paints white text and white icons on it at seven places. Nothing
 * checked whether white is readable on the colour that was chosen, so a company whose brand is
 * yellow, light green or beige — ordinary corporate colours — got a header nobody can read, through a
 * field the product invites them to use.
 *
 * WHAT IS AND IS NOT DECIDED HERE. This picks between two foregrounds by contrast ratio. It does not
 * validate the brand colour, does not warn the operator, and does not adjust the colour: a planning
 * tool has no business overruling a company's brand, and a header that quietly switches to dark text
 * stays usable without anybody having to be told anything.
 */

/** WCAG 2.1 relative luminance of an sRGB channel value in 0..255. */
function channelLuminance(value: number): number {
  const c = value / 255
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
}

/**
 * WCAG 2.1 relative luminance of a `#rrggbb` colour, 0 (black) to 1 (white).
 *
 * Not the naive average of the channels: the eye is far more sensitive to green than to blue, which
 * is what the 0.7152 / 0.0722 weights carry. An average would call a saturated blue "bright" and a
 * yellow "medium", and get the foreground wrong for exactly the colours this function exists for.
 */
export function relativeLuminance(hex: string): number {
  const r = channelLuminance(parseInt(hex.slice(1, 3), 16))
  const g = channelLuminance(parseInt(hex.slice(3, 5), 16))
  const b = channelLuminance(parseInt(hex.slice(5, 7), 16))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** WCAG contrast ratio between two luminances, 1 (identical) to 21 (black on white). */
export function contrastRatio(a: number, b: number): number {
  const lighter = Math.max(a, b)
  const darker = Math.min(a, b)
  return (lighter + 0.05) / (darker + 0.05)
}

/** The dark foreground used when white does not carry enough contrast. */
const DARK_FOREGROUND = '#1a1b1e'

/**
 * Contrast below which white is abandoned: WCAG 2.1 AA for large text.
 *
 * A THRESHOLD, NOT "WHICHEVER MEASURES BETTER", and the difference is not academic. Measured against
 * this module's own numbers, a mid green such as `#2f9e44` gives white 3.45 and dark 5.00 — so a
 * maximise-contrast rule would flip an existing, perfectly legible header to dark text the next time
 * the page loaded. Light text on the brand colour is the near-universal header convention and the look
 * an operator picked their colour for; overturning it is a product decision, not something a
 * readability guard gets to make silently. The guard's job is preventing UNREADABLE, not optimising
 * readable.
 *
 * 3.0 rather than the 4.5 for normal text, because that is the standard's own bar for what the header
 * mostly is: the company name is bold `size="md"` and the icons are 20px. It is deliberately the
 * lower bar — see the note on `readableForeground` for what that leaves open.
 */
const MIN_CONTRAST_FOR_WHITE = 3.0

/** True when a string is a `#rrggbb` colour this module can measure. */
export function isHexColor(value: string): boolean {
  return /^#[0-9a-fA-F]{6}$/.test(value)
}

/**
 * The readable foreground for a brand colour: `'white'` or a near-black.
 *
 * A NON-HEX INPUT ANSWERS WHITE, and that is correct rather than a fallback. The only other thing
 * `primary_color` can be is one of Mantine's own palette names — which is also the shipped default —
 * and the theme resolves those to shade 6, dark enough for white by Mantine's own design. Guessing a
 * luminance from a colour name would be inventing a number.
 *
 * WHAT THIS DOES NOT FIX. Header text smaller than the company name — the user's name is `size="sm"`
 * at weight 500 — needs 4.5, not 3.0. On a brand colour sitting between the two bars, that text is
 * below AA while this function still answers white, on purpose: raising the threshold to 4.5 would
 * flip headers that read perfectly well, and the real answer for those is a larger or heavier label,
 * or a darker brand colour. That is a contrast pass over the header, not a decision this function can
 * make from one colour.
 */
export function readableForeground(brandColor: string): 'white' | typeof DARK_FOREGROUND {
  if (!isHexColor(brandColor)) return 'white'

  const againstWhite = contrastRatio(relativeLuminance(brandColor), relativeLuminance('#ffffff'))
  return againstWhite >= MIN_CONTRAST_FOR_WHITE ? 'white' : DARK_FOREGROUND
}
