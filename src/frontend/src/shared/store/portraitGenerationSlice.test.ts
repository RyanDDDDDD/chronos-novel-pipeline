import { describe, it, expect } from 'vitest'
import portraitGenerationReducer, { selectPortraitGenerating } from '@/shared/store/portraitGenerationSlice'
import { wsEventReceived } from '@/shared/store/wsActions'
import type { RootState } from '@/shared/store/store'

describe('portraitGenerationSlice', () => {
  it('marks a character generating on its started event', () => {
    const state = portraitGenerationReducer(undefined, wsEventReceived({
      type: 'portrait_generation_started', novel_id: 'novel-A', character: '甲',
    }))
    expect(state.byNovelId['novel-A']?.['甲']).toBe('generating')
  })

  it('clears to idle on a successful done event', () => {
    const generating = portraitGenerationReducer(undefined, wsEventReceived({
      type: 'portrait_generation_started', novel_id: 'novel-A', character: '甲',
    }))
    const done = portraitGenerationReducer(generating, wsEventReceived({
      type: 'portrait_generation_done', novel_id: 'novel-A', character: '甲',
      portrait_path: '甲-123.png',
    }))
    expect(done.byNovelId['novel-A']?.['甲']).toBeUndefined()
  })

  it('marks failed on a done event carrying an error', () => {
    const generating = portraitGenerationReducer(undefined, wsEventReceived({
      type: 'portrait_generation_started', novel_id: 'novel-A', character: '甲',
    }))
    const failed = portraitGenerationReducer(generating, wsEventReceived({
      type: 'portrait_generation_done', novel_id: 'novel-A', character: '甲', error: 'network down',
    }))
    expect(failed.byNovelId['novel-A']?.['甲']).toBe('failed')
  })

  it('is isolated per (novelId, character)', () => {
    const state = portraitGenerationReducer(undefined, wsEventReceived({
      type: 'portrait_generation_started', novel_id: 'novel-A', character: '甲',
    }))
    expect(state.byNovelId['novel-A']?.['乙']).toBeUndefined()
    expect(state.byNovelId['novel-B']).toBeUndefined()
  })

  it('selectPortraitGenerating defaults to idle for an unknown character', () => {
    const rootState = { portraitGeneration: { byNovelId: {} } } as RootState
    expect(selectPortraitGenerating('novel-A', '甲')(rootState)).toBe('idle')
  })
})
