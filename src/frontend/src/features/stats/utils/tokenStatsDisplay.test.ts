import { describe, expect, it } from 'vitest'
import {
  formatChapterKey,
  subsystemAccent,
  subsystemLabel,
} from './tokenStatsDisplay'

describe('tokenStatsDisplay', () => {
  it('formatChapterKey 数字键渲染为章节', () => {
    expect(formatChapterKey('6')).toBe('第 6 章')
    expect(formatChapterKey('world')).toBe('world')
  })

  it('subsystemLabel 映射已知子系统', () => {
    expect(subsystemLabel('author_loop')).toBe('主笔')
    expect(subsystemLabel('story_sandbox')).toBe('沙盒试写')
    expect(subsystemLabel('unknown')).toBe('unknown')
  })

  it('story_sandbox 的 accent 和其它子系统不同', () => {
    const accents = new Set([
      subsystemAccent('author_loop'), subsystemAccent('archive'),
      subsystemAccent('setup'), subsystemAccent('story_sandbox'),
    ])
    expect(accents.size).toBe(4)
  })
})
