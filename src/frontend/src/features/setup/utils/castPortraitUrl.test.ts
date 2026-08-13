import { describe, it, expect } from 'vitest'
import { castPortraitUrl } from '@/features/setup/utils/castPortraitUrl'

describe('castPortraitUrl', () => {
  it('builds a URL keyed by character name when portrait_path is set', () => {
    expect(castPortraitUrl('甲', '甲-123.png')).toBe('/api/character-portrait/%E7%94%B2/file?v=%E7%94%B2-123.png')
  })

  it('changes the URL when portrait_path changes, so a regenerated portrait busts the browser cache', () => {
    const before = castPortraitUrl('甲', '甲-123.png')
    const after = castPortraitUrl('甲', '甲-456.png')
    expect(before).not.toBe(after)
  })

  it('returns null when portrait_path is empty', () => {
    expect(castPortraitUrl('甲', undefined)).toBeNull()
    expect(castPortraitUrl('甲', '')).toBeNull()
  })
})
