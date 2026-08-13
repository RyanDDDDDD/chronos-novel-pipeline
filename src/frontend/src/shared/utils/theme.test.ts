/** @vitest-environment jsdom */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  applyTheme,
  persistTheme,
  readStoredTheme,
  resolveInitialTheme,
  toggleTheme,
} from './theme'

const STORAGE_KEY = 'chronos.theme'

function mockLocalStorage() {
  const store = new Map<string, string>()
  const ls = {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => { store.set(k, v) },
    removeItem: (k: string) => { store.delete(k) },
  }
  vi.stubGlobal('localStorage', ls)
  return store
}

describe('theme utils', () => {
  beforeEach(() => {
    mockLocalStorage()
    document.documentElement.classList.remove('dark')
    for (const c of [...document.documentElement.classList]) {
      if (c.startsWith('theme-')) document.documentElement.classList.remove(c)
    }
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    document.documentElement.classList.remove('dark')
    for (const c of [...document.documentElement.classList]) {
      if (c.startsWith('theme-')) document.documentElement.classList.remove(c)
    }
  })

  it('persists and reads theme preference', () => {
    persistTheme('dark')
    expect(readStoredTheme()).toBe('dark')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('dark')
  })

  it('toggles between light and dark', () => {
    expect(toggleTheme('light')).toBe('dark')
    expect(toggleTheme('dark')).toBe('light')
  })

  it('applies theme class and toggles dark when needed', () => {
    applyTheme('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(document.documentElement.classList.contains('theme-dark')).toBe(true)

    applyTheme('solarized-dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(document.documentElement.classList.contains('theme-solarized-dark')).toBe(true)

    applyTheme('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(document.documentElement.classList.contains('theme-light')).toBe(true)
  })

  it('defaults to light when no storage and no dark preference', () => {
    expect(resolveInitialTheme()).toBe('light')
  })
})
