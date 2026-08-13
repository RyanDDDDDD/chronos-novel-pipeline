import { describe, it, expect } from 'vitest'
import {
  locateProseFragment,
  splitProseForSelectionRewriteLoading,
} from './proseSelectionRewriteDisplay'

describe('locateProseFragment', () => {
  it('finds a unique substring', () => {
    expect(locateProseFragment('甲抬起头，看向窗外。', '看向窗外', 5)).toEqual({
      start: 5, end: 9,
    })
  })

  it('disambiguates repeated substrings by anchor offset', () => {
    const prose = '甲看向窗外。乙也看向窗外。'
    expect(locateProseFragment(prose, '看向窗外', 10)).toEqual({ start: 8, end: 12 })
  })

  it('returns null when the substring is missing', () => {
    expect(locateProseFragment('甲抬起头。', '看向窗外', 0)).toBeNull()
  })
})

describe('splitProseForSelectionRewriteLoading', () => {
  it('omits the selected span and keeps stable head/tail inline', () => {
    const prose = '甲抬起头，看向窗外。乙笑了。'
    expect(splitProseForSelectionRewriteLoading(prose, '看向窗外', 5)).toEqual({
      head: '甲抬起头，',
      tail: '。乙笑了。',
    })
  })

  it('places the loader after the first newline following the selection start when it falls inside the span', () => {
    const prose = '甲开头\n选中部分\n看向窗外继续'
    expect(splitProseForSelectionRewriteLoading(prose, '选中部分\n看向窗外', 4)).toEqual({
      head: '甲开头\n选中部分\n',
      tail: '继续',
    })
  })
})
