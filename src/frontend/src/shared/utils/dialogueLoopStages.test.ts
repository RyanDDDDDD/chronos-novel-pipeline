import { describe, it, expect } from 'vitest'
import { DIALOGUE_LOOP_STAGES, DIALOGUE_STAGE_EDGES } from './dialogueLoopStages'

describe('dialogueLoopStages', () => {
  it('包含四节点：导演、正文审核、角色状态推演、场景生图；state_derive 是分支非异步', () => {
    const byId = Object.fromEntries(DIALOGUE_LOOP_STAGES.map(s => [s.id, s]))
    expect(Object.keys(byId).sort()).toEqual(['director', 'review', 'scene_image', 'state_derive'].sort())
    expect(byId['director'].kind).toBe('agent-config')
    expect(byId['review'].kind).toBe('review')
    expect(byId['review'].reviewGroup).toBe('runtime')
    expect(byId['state_derive'].branch).toBe(true)
    expect(byId['state_derive'].async).toBeUndefined()
    expect(DIALOGUE_STAGE_EDGES.filter(e => e.target !== 'scene_image').every(e => !e.async)).toBe(true)
  })

  it('主链路 director→review→state_derive 顺序衔接', () => {
    const chain = ['director', 'review', 'state_derive']
    for (let i = 0; i < chain.length - 1; i++) {
      const edge = DIALOGUE_STAGE_EDGES.find(
        e => e.source === chain[i] && e.target === chain[i + 1],
      )
      expect(edge, `missing edge ${chain[i]}->${chain[i + 1]}`).toBeDefined()
    }
  })

  it('includes an on-demand scene_image branch node wired off review', () => {
    expect(DIALOGUE_LOOP_STAGES.map(s => s.id)).toContain('scene_image')
    const node = DIALOGUE_LOOP_STAGES.find(s => s.id === 'scene_image')!
    expect(node.branch).toBe(true)
    expect(DIALOGUE_STAGE_EDGES).toContainEqual({ source: 'review', target: 'scene_image', async: true })
  })
})
