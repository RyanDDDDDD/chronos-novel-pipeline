/** @vitest-environment jsdom */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  applyReadingFontSize,
  persistReadingFontSize,
  readStoredReadingFontSize,
  resolveInitialReadingFontSize,
} from './readingFontSize'

const STORAGE_KEY = 'chronos.readingFontSize'

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

describe('readingFontSize utils', () => {
  beforeEach(() => {
    mockLocalStorage()
    document.documentElement.style.removeProperty('--reading-font-size')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    document.documentElement.style.removeProperty('--reading-font-size')
  })

  it('persists and reads a valid preference', () => {
    persistReadingFontSize('large')
    expect(readStoredReadingFontSize()).toBe('large')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('large')
  })

  it('returns null for missing or invalid stored values', () => {
    expect(readStoredReadingFontSize()).toBeNull()
    localStorage.setItem(STORAGE_KEY, 'huge')
    expect(readStoredReadingFontSize()).toBeNull()
  })

  it('resolves to stored preference when present, default otherwise', () => {
    expect(resolveInitialReadingFontSize()).toBe('default')
    persistReadingFontSize('xlarge')
    expect(resolveInitialReadingFontSize()).toBe('xlarge')
  })

  it('applies the CSS variable in px for each size', () => {
    applyReadingFontSize('small')
    expect(document.documentElement.style.getPropertyValue('--reading-font-size')).toBe('13px')

    applyReadingFontSize('default')
    expect(document.documentElement.style.getPropertyValue('--reading-font-size')).toBe('14px')

    applyReadingFontSize('large')
    expect(document.documentElement.style.getPropertyValue('--reading-font-size')).toBe('16px')

    applyReadingFontSize('xlarge')
    expect(document.documentElement.style.getPropertyValue('--reading-font-size')).toBe('18px')
  })
})
