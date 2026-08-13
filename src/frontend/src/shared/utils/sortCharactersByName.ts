/** Sort characters by `name`. Storage order is not guaranteed stable across writes (e.g.
 * regenerating a portrait re-appends the touched character at the end server-side), so any
 * UI rendering a character list must impose its own order rather than trust fetch order. */
export function sortCharactersByName<T extends { name: string }>(chars: T[]): T[] {
  return [...chars].sort((a, b) => a.name.localeCompare(b.name))
}
