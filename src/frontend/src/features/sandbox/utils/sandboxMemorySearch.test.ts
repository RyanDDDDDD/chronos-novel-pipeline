import { describe, it, expect } from 'vitest'
import { memorySearchText, memoryMetaLine, formatRecalledMemoryLine } from './sandboxMemorySearch'
import type { SandboxMemoryEntry } from '@/shared/types'

const FULL: SandboxMemoryEntry = {
  id: 'e1', chapter: 3, turnIndex: 2, time: '子夜', location: '藏经阁',
  characters: ['甲', '乙'], summary: '甲把玉佩交给了乙', entities: ['玉佩'], branchId: 'b1',
}

const MINIMAL: SandboxMemoryEntry = {
  id: 'e2', chapter: 1, turnIndex: 0, time: '', location: '',
  characters: [], summary: '旧事件', entities: [], branchId: null,
}

describe('memorySearchText', () => {
  it('大小写不敏感地拼接可搜索字段', () => {
    const text = memorySearchText(FULL)
    expect(text).toContain('甲把玉佩交给了乙')
    expect(text).toContain('藏经阁')
    expect(text).toContain('子夜')
    expect(text).toContain('甲')
    expect(text).toContain('玉佩')
    expect(text).toBe(text.toLowerCase())
  })
})

describe('memoryMetaLine', () => {
  it('全字段都有时渲染章节+时间+地点', () => {
    expect(memoryMetaLine(FULL)).toBe('第3章，子夜，于藏经阁')
  })

  it('缺 time/location 时降级为只有章节', () => {
    expect(memoryMetaLine(MINIMAL)).toBe('第1章')
  })
})

describe('formatRecalledMemoryLine', () => {
  it('全字段都有时包含 meta + summary + 人物', () => {
    const line = formatRecalledMemoryLine(FULL)
    expect(line).toBe('[回忆] 第3章，子夜，于藏经阁：甲把玉佩交给了乙（人物：甲、乙）')
  })

  it('无人物时不追加人物括号', () => {
    const line = formatRecalledMemoryLine(MINIMAL)
    expect(line).toBe('[回忆] 第1章：旧事件')
  })
})
