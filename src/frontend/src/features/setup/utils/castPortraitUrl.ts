/** Resolve cast portrait media URL. The path is keyed by character name (not the stored
 * portrait_path filename) -- the backend looks up the current filename server-side (see
 * GET /api/character-portrait/{name}/file), so a stale client-cached filename never causes a
 * 404. portrait_path is still appended as a `?v=` cache-buster: without it the URL string is
 * identical before and after a regenerate, so React never touches the <img> src attribute and
 * the browser never issues a new request -- the stale image just sits there until a hard reload. */
export function castPortraitUrl(characterName: string, portraitPath?: string): string | null {
  const trimmed = portraitPath?.trim()
  if (!trimmed) return null
  return `/api/character-portrait/${encodeURIComponent(characterName)}/file?v=${encodeURIComponent(trimmed)}`
}
