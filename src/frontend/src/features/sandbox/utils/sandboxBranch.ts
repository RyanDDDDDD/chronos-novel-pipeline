export function storySandboxBranchKey(novelId: string, chapter: number): string {
  return `story-sandbox-branch:${novelId}:${chapter}`
}

export function readStoredBranchId(novelId: string, chapter: number): string | null {
  try {
    return localStorage.getItem(storySandboxBranchKey(novelId, chapter))
  } catch {
    return null
  }
}

export function writeStoredBranchId(novelId: string, chapter: number, branchId: string): void {
  try {
    // localStorage (not sessionStorage): the branch choice should survive closing/restarting
    // the app, same rationale as sandboxMode.ts's mode choice.
    localStorage.setItem(storySandboxBranchKey(novelId, chapter), branchId)
  } catch {
    /* localStorage full/disabled -- branch persistence is a UX optimization, not load-bearing */
  }
}
