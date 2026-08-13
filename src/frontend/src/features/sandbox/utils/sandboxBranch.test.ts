import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { readStoredBranchId, storySandboxBranchKey, writeStoredBranchId } from './sandboxBranch'

// Node's native `localStorage` global (present since Node 22+, stable in the version this repo
// runs) is non-functional without a --localstorage-file flag, and vitest's jsdom environment
// won't overwrite an already-existing global -- so plain `localStorage.clear()` throws. Stub it
// with an in-memory implementation, same as theme.test.ts / readingFontSize.test.ts do.
function mockLocalStorage() {
  const store = new Map<string, string>()
  const ls = {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => { store.set(k, v) },
    removeItem: (k: string) => { store.delete(k) },
    clear: () => { store.clear() },
  }
  vi.stubGlobal('localStorage', ls)
  return store
}

describe('sandboxBranch localStorage', () => {
  beforeEach(() => {
    mockLocalStorage()
    localStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('builds a key scoped to novelId and chapter', () => {
    expect(storySandboxBranchKey('novel-1', 8)).toBe('story-sandbox-branch:novel-1:8')
  })

  it('returns null when nothing stored', () => {
    expect(readStoredBranchId('novel-1', 8)).toBeNull()
  })

  it('roundtrips a written value', () => {
    writeStoredBranchId('novel-1', 8, 'branch-x')
    expect(readStoredBranchId('novel-1', 8)).toBe('branch-x')
  })

  it('does not leak across chapters', () => {
    writeStoredBranchId('novel-1', 8, 'branch-x')
    expect(readStoredBranchId('novel-1', 3)).toBeNull()
  })
})
