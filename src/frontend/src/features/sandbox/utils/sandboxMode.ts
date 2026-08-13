export type SandboxMode = 'chapter' | 'free'

export function storySandboxModeKey(novelId: string): string {
  return `story-sandbox-mode:${novelId}`
}

/** Defaults to 'free' when nothing is stored yet -- the mode toggle always has an active
 * state, there's no "not yet chosen" empty state to represent. */
export function readStoredSandboxMode(novelId: string): SandboxMode {
  const stored = localStorage.getItem(storySandboxModeKey(novelId))
  return stored === 'chapter' ? 'chapter' : 'free'
}

export function writeStoredSandboxMode(novelId: string, mode: 'chapter' | 'free'): void {
  try {
    // localStorage (not sessionStorage): the mode choice should survive closing/restarting the
    // app, unlike the sandbox's other sessionStorage uses (draft input, setup-chat cache) which
    // are deliberately session-scoped recovery for in-progress typing, not a lasting preference.
    localStorage.setItem(storySandboxModeKey(novelId), mode)
  } catch {
    /* localStorage full/disabled -- mode persistence is a UX optimization, not load-bearing */
  }
}

export function effectiveSandboxChapter(mode: SandboxMode, selectedChapter: number): number {
  return mode === 'free' ? 0 : selectedChapter
}
