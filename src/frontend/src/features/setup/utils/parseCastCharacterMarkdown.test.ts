import { describe, it, expect } from 'vitest'
import { buildCastCharacterMarkdown } from '@/features/setup/utils/castCharacterMarkdown'
import { buildCastCharacterPatchPayload } from '@/features/setup/utils/castCharacterPatchPayload'
import { parseCastCharacterMarkdown, parseTagList } from '@/features/setup/utils/parseCastCharacterMarkdown'
import type { CastCharacter } from '@/shared/types'

describe('parseCastCharacterMarkdown', () => {
  it('parses meta, sections, and custom fields', () => {
    const md = `# 甲

**角色类型**：主角  
**性别**：女  
**种族**：人类

## 身份背景

没落贵族

## 因果锚点

- **执念**：复仇

## 着装 DNA

- **招牌常服**：白裙
- **配饰**：银链
- **色系**：（无）
- **材质**：棉

## 爱好

甜食、刺绣

## 口癖

句尾呢

## 特长

剑术
`
    const parsed = parseCastCharacterMarkdown(md, {
      customFieldSpecs: [{ name: '特长', required: true, timeline_delta: true }],
    })
    expect(parsed.role).toBe('主角')
    expect(parsed.gender).toBe('female')
    expect(parsed.race).toBe('人类')
    expect(parsed.identity_background).toBe('没落贵族')
    expect(parsed.causal_anchors).toEqual({ 执念: '复仇' })
    expect(parsed.clothing_dna?.signature_outfit).toBe('白裙')
    expect(parsed.hobbies).toEqual(['甜食', '刺绣'])
    expect(parsed.customFields?.['特长']).toBe('剑术')
  })

  it('roundtrips editable fields through build → parse → payload', () => {
    const baseline = {
      name: '甲',
      role: '主角',
      gender: 'female',
      race: '人类',
      identity: '身份短句',
      identity_background: '背景',
      personality: '嘴硬',
      causal_anchors: { 执念: '复仇' },
      physique: { 身高: '165cm' },
      clothing_dna: {
        signature_outfit: '白裙',
        accessories: ['银链'],
        color_palette: ['白'],
        materials_preference: ['棉'],
      },
      hobbies: ['甜食'],
      verbal_tic: '呢',
      portrait_visual_tags: '1girl, silver hair',
      sliders: { 沦陷度: { level: 1, text: '戒备', levels: { '0': '冷', '1': '热' } } },
    } as CastCharacter

    const md = buildCastCharacterMarkdown(baseline, [])
    const edited = md
      .replace('## 身份背景\n\n背景', '## 身份背景\n\n背景已改')
      .replace('**招牌常服**：白裙', '**招牌常服**：黑裙')
    const parsed = parseCastCharacterMarkdown(edited, { baseline })
    const payload = buildCastCharacterPatchPayload(baseline, parsed, [])

    expect(payload.identity_background).toBe('背景已改')
    expect(payload.clothing_signature_outfit).toBe('黑裙')
    expect(payload.sliders).toEqual(baseline.sliders)
    expect(payload.portrait_visual_tags).toBe('1girl, silver hair')
  })

  it('parses and roundtrips a manually edited portrait visual tags section', () => {
    const baseline = {
      name: '甲', portrait_visual_tags: '1girl, silver hair',
    } as CastCharacter
    const md = buildCastCharacterMarkdown(baseline, [])
    const edited = md.replace('1girl, silver hair', '1girl, golden hair')

    const parsed = parseCastCharacterMarkdown(edited, { baseline })
    expect(parsed.portrait_visual_tags).toBe('1girl, golden hair')

    const payload = buildCastCharacterPatchPayload(baseline, parsed, [])
    expect(payload.portrait_visual_tags).toBe('1girl, golden hair')
  })

  it('parseTagList treats empty marker as empty list', () => {
    expect(parseTagList('（无）')).toEqual([])
    expect(parseTagList('a、b')).toEqual(['a', 'b'])
  })
})
