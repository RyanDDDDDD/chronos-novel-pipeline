//Each novel records its own selected chapter, and the key is distinguished by novelId.
const PREFIX = 'chronos:chapter:'

export function readStoredChapter(novelId: string): number {
  if (!novelId) return 1
  try {
    const raw = localStorage.getItem(PREFIX + novelId)
    const n = raw !== null ? Number(raw) : NaN
    return Number.isInteger(n) && n > 0 ? n : 1
  } catch {
    return 1
  }
}

export function persistChapter(novelId: string, chapter: number): void {
  if (!novelId) return
  try {
    localStorage.setItem(PREFIX + novelId, String(chapter))
  } catch {
    // quota / private browsing — ignore
  }
}
