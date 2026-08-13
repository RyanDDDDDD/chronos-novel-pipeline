import { describe, it, expect } from 'vitest'
import { countManuscriptChars } from '@/shared/utils/manuscriptText'

describe('countManuscriptChars', () => {
  it('去空白计字符', () => {
    expect(countManuscriptChars('甲 乙\n丙')).toBe(3)
    expect(countManuscriptChars('')).toBe(0)
  })
})
