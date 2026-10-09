/** Load a complete collection before local filtering, rather than silently returning its first page. */
export async function allPages<T>(
  fetchPage: (offset: number) => Promise<{ items: T[]; total: number }>,
): Promise<T[]> {
  const items: T[] = []
  let total: number
  do {
    const page = await fetchPage(items.length)
    total = page.total
    if (page.items.length === 0 && items.length < total) {
      throw new Error('The list ended before all entries were loaded')
    }
    items.push(...page.items)
  } while (items.length < total)
  return items
}
