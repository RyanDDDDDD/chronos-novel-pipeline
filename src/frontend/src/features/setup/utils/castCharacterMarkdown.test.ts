import { describe, it, expect } from 'vitest'
import { buildCastCharacterMarkdown } from '@/features/setup/utils/castCharacterMarkdown'
import type { CastCharacter, RelationshipGraph } from '@/shared/types'

describe('buildCastCharacterMarkdown', () => {
  it('includes identity, clothing dna, and custom fields', () => {
    const char = {
      name: '甲',
      role: '主角',
      gender: 'female',
      identity_background: '没落贵族',
      clothing_dna: {
        signature_outfit: '白裙',
        accessories: ['银链'],
        color_palette: ['白'],
        materials_preference: ['棉'],
      },
      特长: '剑术',
    } as CastCharacter
    const md = buildCastCharacterMarkdown(char, [{ name: '特长', required: true, timeline_delta: true }])
    expect(md).toContain('# 甲')
    expect(md).toContain('## 身份背景')
    expect(md).toContain('没落贵族')
    expect(md).toContain('招牌常服')
    expect(md).toContain('白裙')
    expect(md).toContain('## 特长')
  })

  it('includes hobbies joined in one paragraph', () => {
    const char = {
      name: '甲',
      identity_background: '没落贵族之女，寄人篱下',
      hobbies: ['爱吃甜食', '喜欢刺绣'],
    } as CastCharacter
    const md = buildCastCharacterMarkdown(char, [])
    expect(md).toContain('## 爱好')
    expect(md).toContain('爱吃甜食、喜欢刺绣')
  })

  it('includes portrait visual tags when cached, omits the section otherwise', () => {
    const withTags = { name: '甲', portrait_visual_tags: '1girl, silver hair' } as CastCharacter
    const md = buildCastCharacterMarkdown(withTags, [])
    expect(md).toContain('## 生图提示词')
    expect(md).toContain('1girl, silver hair')

    const withoutTags = { name: '甲' } as CastCharacter
    expect(buildCastCharacterMarkdown(withoutTags, [])).not.toContain('生图提示词')
  })

  it('includes the identity anchor section when set, omits it otherwise', () => {
    const withAnchor = {
      name: '甲', portrait_identity_tags: 'shiroko (blue archive), blue archive',
    } as CastCharacter
    const md = buildCastCharacterMarkdown(withAnchor, [])
    expect(md).toContain('## 形象锚定')
    expect(md).toContain('shiroko (blue archive), blue archive')

    expect(buildCastCharacterMarkdown({ name: '甲' } as CastCharacter, [])).not.toContain('形象锚定')
  })

  it('includes slider ladder and relationships', () => {
    const char = {
      name: '甲',
      sliders: {
        沦陷度: {
          level: 1,
          text: '初见时略带戒备',
          levels: { '0': '戒备', '1': '动摇', '2': '沦陷' },
        },
      },
    } as CastCharacter
    const graph: RelationshipGraph = {
      edges: {
        e1: {
          from: '甲',
          to: '乙',
          nature: '恋人',
          from_ref_terms: ['你'],
          to_ref_terms: ['她'],
          relationship_anchor: '青梅竹马',
        },
      },
    }
    const md = buildCastCharacterMarkdown(char, {
      relationshipGraph: graph,
      portraitUrl: '/media/portraits/a.png',
    })
    expect(md).toContain('![甲](/media/portraits/a.png)')
    expect(md).toContain('## 成长轴')
    expect(md).toContain('**Lv.1：动摇**（当前）')
    expect(md).toContain('## 关系')
    expect(md).toContain('→ **乙**（恋人）')
    expect(md).toContain('青梅竹马')
  })
})
