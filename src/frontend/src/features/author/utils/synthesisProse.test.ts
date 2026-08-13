import { describe, expect, it } from 'vitest'
import { stripSynthesisProse } from '@/features/author/utils/synthesisProse'

describe('stripSynthesisProse', () => {
  it('去掉 # 合成正文 标题行', () => {
    expect(stripSynthesisProse('# 合成正文\n\n茶室很暗。')).toBe('茶室很暗。')
    expect(stripSynthesisProse('#合成正文\n正文')).toBe('正文')
  })

  it('无标记时原样返回', () => {
    expect(stripSynthesisProse('纯正文')).toBe('纯正文')
  })

  it('流式前缀未打完时不露出', () => {
    expect(stripSynthesisProse('#')).toBe('')
    expect(stripSynthesisProse('# 合')).toBe('')
    expect(stripSynthesisProse('#合成')).toBe('')
  })
})
