import { describe, it, expect } from 'vitest'
import { buildCharacterArchiveMarkdown } from '@/shared/utils/characterArchiveMarkdown'
import type { CharacterArchive, RelationshipGraph } from '@/shared/types'

describe('buildCharacterArchiveMarkdown', () => {
  it('includes meta, sliders, physique, and archive-only fields', () => {
    const char: CharacterArchive = {
      name: '甲',
      role: '主角',
      location: '藏经阁',
      gender: 'female',
      identity_background: '没落贵族',
      personality: '外冷内热',
      causal_anchors: { 契约: '血契' },
      sliders: { 侵蚀度: { value: 1, label: '动摇' } },
      physique: { horns: '小角' },
      hobbies: ['刺绣'],
      verbal_tic: '呢',
      address_ref: { _default: ['你'] },
      self_ref: ['妾身'],
      thought_process: { delta: 'd', escalation: 'e' },
    }
    const md = buildCharacterArchiveMarkdown(char)
    expect(md).toContain('# 甲')
    expect(md).toContain('**地点**：藏经阁')
    expect(md).toContain('## 身份背景')
    expect(md).toContain('## 成长轴')
    expect(md).toContain('### 侵蚀度 · Lv.1')
    expect(md).toContain('动摇')
    expect(md).toContain('## 体格')
    expect(md).toContain('**horns**：小角')
    expect(md).toContain('## 称呼')
    expect(md).toContain('## 内心活动')
  })

  it('includes relationships', () => {
    const char: CharacterArchive = {
      name: '甲',
      role: '主角',
      causal_anchors: {},
      sliders: {},
    }
    const graph: RelationshipGraph = {
      edges: {
        e1: {
          from: '甲',
          to: '乙',
          nature: '恋人',
          relationship_anchor: '青梅竹马',
        },
      },
    }
    const md = buildCharacterArchiveMarkdown(char, graph)
    expect(md).toContain('## 关系')
    expect(md).toContain('→ **乙**（恋人）')
  })
})
