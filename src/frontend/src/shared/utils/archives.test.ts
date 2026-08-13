import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchSandboxCastArchives } from '@/shared/utils/archives'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('fetchSandboxCastArchives', () => {
  it('URL-encodes names via URLSearchParams', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: async () => ({ characters: [] }),
    } as Response))
    await fetchSandboxCastArchives(2, ['甲,乙', '丙&丁'], 'novel-x')
    const url = String(vi.mocked(fetch).mock.calls[0]?.[0])
    const parsed = new URL(url, 'http://localhost')
    expect(parsed.searchParams.get('chapter')).toBe('2')
    expect(parsed.searchParams.get('novel_id')).toBe('novel-x')
    expect(parsed.searchParams.get('names')).toBe('甲,乙,丙&丁')
    expect(url).toContain('names=')
    expect(url).not.toContain('names=甲,乙,丙&丁')
  })
})
