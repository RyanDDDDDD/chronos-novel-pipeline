/** Filter characters whose `name` contains `query` (case-insensitive, trimmed). Empty query returns all. */
export function filterCharactersByName<T extends { name: string }>(chars: T[], query: string): T[] {
  const q = query.trim().toLowerCase()
  if (!q) return chars
  return chars.filter((c) => c.name.toLowerCase().includes(q))
}
