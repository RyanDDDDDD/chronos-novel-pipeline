import { describe, it, expect } from 'vitest'
import { chaptersKey, authorSceneImagesKey, authorSceneImagesPrefixKey } from './keys'

describe('pipeline/chapters query keys', () => {
  it('chaptersKey 带 novelId', () => {
    expect(chaptersKey('n1')).toEqual(['chapters', 'n1'])
  })
})

describe('author scene-image query keys', () => {
  it('authorSceneImagesKey 带 novelId + chapter，以 prefix key 开头', () => {
    expect(authorSceneImagesKey('n1', 6)).toEqual(['author', 'scene-images', 'n1', 6])
  })

  it('authorSceneImagesPrefixKey 是 authorSceneImagesKey 的前缀（用于失效所有 novelId/chapter 变体）', () => {
    expect(authorSceneImagesKey('n1', 6).slice(0, authorSceneImagesPrefixKey.length)).toEqual(authorSceneImagesPrefixKey)
  })
})
