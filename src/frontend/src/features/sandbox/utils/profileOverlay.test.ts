import { describe, it, expect } from 'vitest'
import { mergeSandboxProfileOverlay, computeFieldKeys } from '@/features/sandbox/utils/profileOverlay'
import type { CharacterArchive } from '@/shared/types'

const baseArchive: CharacterArchive = {
  name: '甲', role: '同质堕落型', causal_anchors: {},
  sliders: { 侵蚀度: { value: 1, label: '动摇' } },
  physique: { horns: '有一对小角' },
  personality: '外冷内热',
  hobbies: ['炼金'],
}

describe('mergeSandboxProfileOverlay', () => {
  it('converts a {level,text} slider overlay entry into {value,label} and merges per axis', () => {
    const merged = mergeSandboxProfileOverlay(baseArchive, {
      sliders: { 侵蚀度: { level: 3, text: '沦陷' } },
    })
    expect(merged.sliders).toEqual({ 侵蚀度: { value: 3, label: '沦陷' } })
  })

  it('merges physique per slot without dropping other slots', () => {
    const merged = mergeSandboxProfileOverlay(baseArchive, { physique: { tail: '长出了尾巴' } })
    expect(merged.physique).toEqual({ horns: '有一对小角', tail: '长出了尾巴' })
  })

  it('replaces hobbies wholesale', () => {
    const merged = mergeSandboxProfileOverlay(baseArchive, { hobbies: ['剑术'] })
    expect(merged.hobbies).toEqual(['剑术'])
  })

  it('replaces scalar fields wholesale', () => {
    const merged = mergeSandboxProfileOverlay(baseArchive, { personality: '疯狂' })
    expect(merged.personality).toBe('疯狂')
  })

  it('does not mutate the input archive', () => {
    mergeSandboxProfileOverlay(baseArchive, { personality: '疯狂' })
    expect(baseArchive.personality).toBe('外冷内热')
  })
})

describe('computeFieldKeys', () => {
  it('expands sliders into per-axis keys', () => {
    expect(computeFieldKeys({ sliders: { 侵蚀度: { level: 1, text: 'x' }, 抗拒度: { level: 2, text: 'y' } } }))
      .toEqual(new Set(['sliders:侵蚀度', 'sliders:抗拒度']))
  })

  it('expands physique into per-slot keys', () => {
    expect(computeFieldKeys({ physique: { horns: 'x', tail: 'y' } }))
      .toEqual(new Set(['physique:horns', 'physique:tail']))
  })

  it('keeps scalar/hobbies fields as their own key', () => {
    expect(computeFieldKeys({ personality: '疯狂', hobbies: ['剑术'] }))
      .toEqual(new Set(['personality', 'hobbies']))
  })
})
