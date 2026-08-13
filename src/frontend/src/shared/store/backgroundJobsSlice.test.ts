import { describe, it, expect } from 'vitest'
import backgroundJobsReducer, { backgroundJobsSnapshotLoaded, selectBackgroundJobs } from '@/shared/store/backgroundJobsSlice'
import { wsEventReceived } from '@/shared/store/wsActions'
import type { RootState } from '@/shared/store/store'

describe('backgroundJobsSlice', () => {
  it('marks skeleton review active on its started event', () => {
    const state = backgroundJobsReducer(undefined, wsEventReceived({
      type: 'skeleton_review_started', novel_id: 'novel-A',
    }))
    expect(state.byNovelId['novel-A'].skeletonReviewActive).toBe(true)
  })

  it('clears skeleton review on its done event', () => {
    const running = backgroundJobsReducer(undefined, wsEventReceived({
      type: 'skeleton_review_started', novel_id: 'novel-A',
    }))
    const done = backgroundJobsReducer(running, wsEventReceived({
      type: 'skeleton_review_done', novel_id: 'novel-A',
    }))
    expect(done.byNovelId['novel-A'].skeletonReviewActive).toBe(false)
  })

  it('tracks timeline cascade independently of skeleton review', () => {
    const state = backgroundJobsReducer(undefined, wsEventReceived({
      type: 'timeline_cascade_started', novel_id: 'novel-A',
    }))
    expect(state.byNovelId['novel-A'].timelineCascadeActive).toBe(true)
    expect(state.byNovelId['novel-A'].skeletonReviewActive).toBe(false)
  })

  it('restarted events do not change the active flag', () => {
    const running = backgroundJobsReducer(undefined, wsEventReceived({
      type: 'skeleton_review_started', novel_id: 'novel-A',
    }))
    const restarted = backgroundJobsReducer(running, wsEventReceived({
      type: 'skeleton_review_restarted', novel_id: 'novel-A',
    }))
    expect(restarted.byNovelId['novel-A'].skeletonReviewActive).toBe(true)
  })

  it('ignores events without a novel_id', () => {
    const state = backgroundJobsReducer(undefined, wsEventReceived({ type: 'skeleton_review_started' }))
    expect(state.byNovelId).toEqual({})
  })

  it('is isolated per novel', () => {
    const state = backgroundJobsReducer(undefined, wsEventReceived({
      type: 'timeline_cascade_started', novel_id: 'novel-A',
    }))
    expect(state.byNovelId['novel-B']).toBeUndefined()
  })

  it('seeds active flags from a snapshot', () => {
    const state = backgroundJobsReducer(undefined, backgroundJobsSnapshotLoaded({
      'novel-A': { skeleton_review: true, timeline_cascade: false, world_review: false, character_review: false },
      'novel-B': { skeleton_review: false, timeline_cascade: false, world_review: false, character_review: false },
    }))
    expect(state.byNovelId['novel-A']).toEqual({
      skeletonReviewActive: true, timelineCascadeActive: false, worldReviewActive: false, characterReviewActive: false,
    })
    expect(state.byNovelId['novel-B']).toEqual({
      skeletonReviewActive: false, timelineCascadeActive: false, worldReviewActive: false, characterReviewActive: false,
    })
  })

  it('snapshot clears stale active flags when backend reports idle', () => {
    const running = backgroundJobsReducer(undefined, wsEventReceived({
      type: 'skeleton_review_started', novel_id: 'novel-A',
    }))
    const synced = backgroundJobsReducer(running, backgroundJobsSnapshotLoaded({
      'novel-A': { skeleton_review: false, timeline_cascade: false, world_review: false, character_review: false },
    }))
    expect(synced.byNovelId['novel-A'].skeletonReviewActive).toBe(false)
  })

  it('tracks world review independently', () => {
    const state = backgroundJobsReducer(undefined, wsEventReceived({
      type: 'world_review_started', novel_id: 'novel-A',
    }))
    expect(state.byNovelId['novel-A'].worldReviewActive).toBe(true)
    expect(state.byNovelId['novel-A'].skeletonReviewActive).toBe(false)
  })

  it('selectBackgroundJobs defaults to all-false for an unknown novel', () => {
    const rootState = { backgroundJobs: { byNovelId: {} } } as RootState
    expect(selectBackgroundJobs('unknown')(rootState)).toEqual({
      skeletonReviewActive: false, timelineCascadeActive: false, worldReviewActive: false, characterReviewActive: false,
    })
  })

  it('tracks character review independently', () => {
    const state = backgroundJobsReducer(undefined, wsEventReceived({
      type: 'character_review_started', novel_id: 'novel-A',
    }))
    expect(state.byNovelId['novel-A'].characterReviewActive).toBe(true)
    expect(state.byNovelId['novel-A'].worldReviewActive).toBe(false)
  })

  it('clears character review on its done event', () => {
    const running = backgroundJobsReducer(undefined, wsEventReceived({
      type: 'character_review_started', novel_id: 'novel-A',
    }))
    const done = backgroundJobsReducer(running, wsEventReceived({
      type: 'character_review_done', novel_id: 'novel-A',
    }))
    expect(done.byNovelId['novel-A'].characterReviewActive).toBe(false)
  })

  it('seeds character review from a snapshot', () => {
    const state = backgroundJobsReducer(undefined, backgroundJobsSnapshotLoaded({
      'novel-A': {
        skeleton_review: false, timeline_cascade: false, world_review: false,
        character_review: true,
      },
    }))
    expect(state.byNovelId['novel-A'].characterReviewActive).toBe(true)
  })
})
