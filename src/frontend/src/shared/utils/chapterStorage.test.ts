import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { readStoredChapter, persistChapter, clearStoredChapter } from './chapterStorage'

// Node's native localStorage is non-functional here; stub an in-memory one (same as
// readingFontSize.test.ts / sandboxBranch.test.ts).
function mockLocalStorage() {
  const store = new Map<string, string>()
  const ls = {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => { store.set(k, v) },
    removeItem: (k: string) => { store.delete(k) },
    clear: () => { store.clear() },
  }
  vi.stubGlobal('localStorage', ls)
}

describe('clearStoredChapter', () => {
  beforeEach(() => {
    mockLocalStorage()
    localStorage.clear()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('removes the stored chapter for this novel', () => {
    persistChapter('novel-a', 5)
    clearStoredChapter('novel-a')
    expect(readStoredChapter('novel-a')).toBe(1) // falls back to default
  })

  it('does not affect other novels', () => {
    persistChapter('novel-a', 5)
    persistChapter('novel-b', 7)
    clearStoredChapter('novel-a')
    expect(readStoredChapter('novel-b')).toBe(7)
  })
})
