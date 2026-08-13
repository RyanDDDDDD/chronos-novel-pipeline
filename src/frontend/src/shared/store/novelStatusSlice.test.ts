import { describe, it, expect } from 'vitest'
import novelStatusReducer, {
  novelStatusSnapshotLoaded, novelStatusAcknowledged,
} from '@/shared/store/novelStatusSlice'
import { wsEventReceived } from '@/shared/store/wsActions'

describe('novelStatusSlice', () => {
  it('marks a novel running on its start event', () => {
    const state = novelStatusReducer(undefined, wsEventReceived({
      type: 'story_sandbox_start', novel_id: 'novel-A',
    }))
    expect(state.byNovelId['novel-A']).toBe('running')
  })

  it('marks a novel done on its terminal success event', () => {
    const state = novelStatusReducer(undefined, wsEventReceived({
      type: 'setup_chat_done', novel_id: 'novel-A',
    }))
    expect(state.byNovelId['novel-A']).toBe('done')
  })

  it('marks a novel error on its error event and does not auto-clear', () => {
    const state = novelStatusReducer(undefined, wsEventReceived({
      type: 'story_sandbox_error', novel_id: 'novel-A',
    }))
    expect(state.byNovelId['novel-A']).toBe('error')
  })

  it('ignores events without a novel_id', () => {
    const state = novelStatusReducer(undefined, wsEventReceived({ type: 'story_sandbox_start' }))
    expect(state.byNovelId).toEqual({})
  })

  it('seeds running status from a snapshot', () => {
    const state = novelStatusReducer(undefined, novelStatusSnapshotLoaded({
      'novel-A': { author_loop: true, setup_chat: false, story_sandbox: false },
      'novel-B': { author_loop: false, setup_chat: false, story_sandbox: false },
    }))
    expect(state.byNovelId['novel-A']).toBe('running')
    expect(state.byNovelId['novel-B']).toBeUndefined()
  })

  it('acknowledged clears a novel back to idle', () => {
    const running = novelStatusReducer(undefined, wsEventReceived({
      type: 'story_sandbox_start', novel_id: 'novel-A',
    }))
    const cleared = novelStatusReducer(running, novelStatusAcknowledged({ novelId: 'novel-A' }))
    expect(cleared.byNovelId['novel-A']).toBeUndefined()
  })
})
