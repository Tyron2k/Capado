/**
 * Turning a Select's value into what the API expects for an optional site.
 *
 * In its own file because a component module may only export components (react-refresh), and
 * because this one line needs to be testable on its own: while it was inline in the form's JSX it
 * could only be reached through a Select interaction, and the rendering test that tried to cover it
 * still passed with the mapping deleted.
 */

/**
 * Map a site Select's value to the API representation.
 *
 * Mantine yields '' when a clearable Select is cleared, and '' is NOT null: sent as-is it reaches
 * the API as an empty string, which fails UUID validation — and on an endpoint that coerces instead
 * of rejecting, it would leave the old site in place while the user watches the field go blank and
 * the save report success.
 *
 * null is the deliberate output for every empty case, because null is meaningful here: it REMOVES
 * the site. Omitting the key instead would mean "leave it alone", which is a different request.
 */
export function normalizeSiteId(value: string | null | undefined): string | null {
  return value ? value : null
}
