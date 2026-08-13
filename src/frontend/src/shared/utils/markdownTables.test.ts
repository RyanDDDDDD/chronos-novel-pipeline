import { describe, it, expect } from 'vitest'
import { repairMarkdownTables, splitInlineTableRows, tableSeparatorColumnCount } from './markdownTables'

describe('tableSeparatorColumnCount', () => {
  it('recognizes GFM separator rows', () => {
    expect(tableSeparatorColumnCount('|:--|:--|:--|:--|')).toBe(4)
    expect(tableSeparatorColumnCount('| --- | :---: | ---: |')).toBe(3)
  })

  it('rejects data rows', () => {
    expect(tableSeparatorColumnCount('| 1 | 标题 | 场景 |')).toBeNull()
  })
})

describe('repairMarkdownTables', () => {
  it('inserts header when separator has no header row above', () => {
    const broken = [
      '|:--|:--|:--|:--|',
      '| 1 | 甲 | 地点A | 概述一 |',
      '| 2 | 乙 | 地点B | 概述二 |',
    ].join('\n')
    const fixed = repairMarkdownTables(broken)
    expect(fixed.startsWith('| 列1 | 列2 | 列3 | 列4 |')).toBe(true)
    expect(fixed).toContain('|:--|:--|:--|:--|')
    expect(fixed).toContain('| 1 | 甲 |')
  })

  it('does not duplicate header when already present', () => {
    const ok = [
      '| 章 | 标题 | 场景 | 概要 |',
      '|:--|:--|:--|:--|',
      '| 1 | 甲 | 地点A | 概述 |',
    ].join('\n')
    expect(repairMarkdownTables(ok)).toBe(ok)
  })

  it('leaves non-table markdown unchanged', () => {
    const text = '普通段落\n\n- 列表项'
    expect(repairMarkdownTables(text)).toBe(text)
  })

  it('splits inline concatenated table rows and inserts separator', () => {
    const broken =
      '| Stage | 场景 | 内容 | | Stage 1 | 部活室·独处 | 放学后爱丽丝 | | Stage 2 | 部活室·全员 | 桃井到部 |'
    const fixed = repairMarkdownTables(broken)
    expect(fixed).toContain('| Stage | 场景 | 内容 |')
    expect(fixed).toContain('| --- | --- | --- |')
    expect(fixed).toContain('| Stage 1 | 部活室·独处 | 放学后爱丽丝 |')
    expect(fixed).toContain('| Stage 2 | 部活室·全员 | 桃井到部 |')
    expect(fixed.split('\n').length).toBe(4)
    expect(fixed.split('\n').filter((l) => tableSeparatorColumnCount(l) !== null).length).toBe(1)
  })

  it('preserves title paragraph before broken inline table', () => {
    const broken = [
      '第1章《游戏机的秘密》',
      '',
      '| Stage | 场景 | 内容 | | Stage 1 | 甲 | 概述 |',
    ].join('\n')
    const fixed = repairMarkdownTables(broken)
    expect(fixed.startsWith('第1章《游戏机的秘密》')).toBe(true)
    expect(fixed).toContain('| --- | --- | --- |')
  })

  it('inserts only one separator for multi-line table without separator row', () => {
    const broken = [
      '| 章 | 标题 | 核心 |',
      '| 1 | 日常的裂隙 | 概述一 |',
      '| 2 | 柜中伏击 | 概述二 |',
      '| 3 | 上下夹攻 | 概述三 |',
    ].join('\n')
    const fixed = repairMarkdownTables(broken)
    expect(fixed.split('\n').filter((l) => tableSeparatorColumnCount(l) !== null).length).toBe(1)
    expect(fixed).toContain('| 1 | 日常的裂隙 | 概述一 |')
    expect(fixed).toContain('| 3 | 上下夹攻 | 概述三 |')
  })
})

describe('splitInlineTableRows', () => {
  it('splits multiple rows on one line', () => {
    const line = '| A | B | | C | D |'
    expect(splitInlineTableRows(line)).toEqual(['| A | B |', '| C | D |'])
  })

  it('leaves single-row lines unchanged', () => {
    const line = '| A | B | C |'
    expect(splitInlineTableRows(line)).toEqual([line])
  })
})
