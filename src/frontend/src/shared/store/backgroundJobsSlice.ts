import { createSlice } from '@reduxjs/toolkit'
import type { RootState } from '@/shared/store/store'
import { wsEventReceived } from '@/shared/store/wsActions'

interface NovelJobFlags {
  skeletonReviewActive: boolean
  timelineCascadeActive: boolean
  worldReviewActive: boolean
}

const START_TYPES: Record<string, keyof NovelJobFlags> = {
  skeleton_review_started: 'skeletonReviewActive',
  timeline_cascade_started: 'timelineCascadeActive',
  world_review_started: 'worldReviewActive',
}
const DONE_TYPES: Record<string, keyof NovelJobFlags> = {
  skeleton_review_done: 'skeletonReviewActive',
  timeline_cascade_done: 'timelineCascadeActive',
  world_review_done: 'worldReviewActive',
}
// restarted events don't change the flag -- it was already true and stays true through a
// cancel-then-restart; they exist purely for callers that want to react to the transition
// itself (none currently do on the frontend, but the WS event is broadcast regardless.

interface BackgroundJobsState {
  byNovelId: Record<string, NovelJobFlags>
}

const initialState: BackgroundJobsState = { byNovelId: {} }

// Stable reference for selectBackgroundJobs' fallback -- a fresh object literal there would
// make useSelector see a "new" result on every call for a novel with no entry yet, triggering
// react-redux's unmemoized-selector warning and unnecessary rerenders.
const DEFAULT_FLAGS: NovelJobFlags = {
  skeletonReviewActive: false,
  timelineCascadeActive: false,
  worldReviewActive: false,
}

function ensure(state: BackgroundJobsState, novelId: string): NovelJobFlags {
  return state.byNovelId[novelId] ??= {
    skeletonReviewActive: false,
    timelineCascadeActive: false,
    worldReviewActive: false,
  }
}

const backgroundJobsSlice = createSlice({
  name: 'backgroundJobs',
  initialState,
  reducers: {
    /** Seeds initial state from GET /api/novels/status on app mount -- mirrors
     * novelStatusSnapshotLoaded's rationale: lifecycle WS events only carry future
     * transitions, not what's already running when the page loads. */
    backgroundJobsSnapshotLoaded: (
      state,
      action: {
        payload: Record<string, {
          skeleton_review: boolean
          timeline_cascade: boolean
          world_review: boolean
        }>
      },
    ) => {
      for (const [novelId, flags] of Object.entries(action.payload)) {
        const entry = ensure(state, novelId)
        entry.skeletonReviewActive = flags.skeleton_review
        entry.timelineCascadeActive = flags.timeline_cascade
        entry.worldReviewActive = flags.world_review
      }
    },
  },
  extraReducers: (builder) => {
    builder.addCase(wsEventReceived, (state, action) => {
      const { type, novel_id: novelId } = action.payload
      if (!novelId) return
      const startKey = START_TYPES[type]
      const doneKey = DONE_TYPES[type]
      if (startKey) {
        ensure(state, novelId)[startKey] = true
      } else if (doneKey) {
        ensure(state, novelId)[doneKey] = false
      }
    })
  },
})

export const { backgroundJobsSnapshotLoaded } = backgroundJobsSlice.actions
export default backgroundJobsSlice.reducer

export const selectBackgroundJobs = (novelId: string) => (state: RootState): NovelJobFlags =>
  state.backgroundJobs.byNovelId[novelId] ?? DEFAULT_FLAGS
