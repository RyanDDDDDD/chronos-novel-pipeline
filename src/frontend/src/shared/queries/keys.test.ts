import { describe, it, expect } from 'vitest'
import { chaptersKey } from './keys'

describe('pipeline/chapters query keys', () => {
  it('chaptersKey 带 novelId', () => {
    expect(chaptersKey('n1')).toEqual(['chapters', 'n1'])
  })
})
