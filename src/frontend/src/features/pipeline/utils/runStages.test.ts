import { describe, it, expect } from 'vitest'
import { SANDBOX_RUN_STAGES, SANDBOX_RUN_EDGES } from './runStages'

describe('sandboxRunStages', () => {
  it('10 个节点，id 唯一', () => {
    expect(SANDBOX_RUN_STAGES).toHaveLength(10)
    expect(new Set(SANDBOX_RUN_STAGES.map(s => s.id)).size).toBe(10)
    expect(SANDBOX_RUN_STAGES.map(s => s.id)).not.toContain('event_log')
    expect(SANDBOX_RUN_STAGES.map(s => s.id)).toEqual(
      expect.arrayContaining([
        'summary_fold', 'event_extract', 'dialogue_draft', 'identify_cast', 'selection_rewrite',
      ]),
    )
  })

  it('每条边的 source/target 都是已声明的节点 id', () => {
    const ids = new Set(SANDBOX_RUN_STAGES.map(s => s.id))
    for (const e of SANDBOX_RUN_EDGES) {
      expect(ids.has(e.source)).toBe(true)
      expect(ids.has(e.target)).toBe(true)
    }
  })

  it('suggest 是四路 fan-in（derive_char/derive_scene/profile_mutate/summary_fold 都指向它）', () => {
    const intoSuggest = SANDBOX_RUN_EDGES.filter(e => e.target === 'suggest').map(e => e.source)
    expect(new Set(intoSuggest)).toEqual(
      new Set(['derive_char', 'derive_scene', 'profile_mutate', 'summary_fold']),
    )
  })

  it('identify_cast/selection_rewrite 用虚线（async: true）分别指向 dialogue_draft/prose', () => {
    const identifyEdge = SANDBOX_RUN_EDGES.find(e => e.source === 'identify_cast')
    expect(identifyEdge).toEqual({ source: 'identify_cast', target: 'dialogue_draft', async: true })
    const selectionRewriteEdge = SANDBOX_RUN_EDGES.find(e => e.target === 'selection_rewrite')
    expect(selectionRewriteEdge).toEqual({ source: 'prose', target: 'selection_rewrite', async: true })
  })
})
