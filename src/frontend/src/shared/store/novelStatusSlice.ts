import { createSlice } from '@reduxjs/toolkit'
import type { RootState } from '@/shared/store/store'
import { wsEventReceived } from '@/shared/store/wsActions'

export type NovelRunStatus = 'idle' | 'running' | 'done' | 'error'

const START_TYPES = new Set([
  'author_loop_start', 'setup_chat_start', 'story_sandbox_start',
])
const DONE_TYPES = new Set([
  'author_loop_done', 'setup_chat_final', 'setup_chat_done',
  'story_sandbox_done', 'story_sandbox_rewrite_done',
  'story_sandbox_suggestions_regenerated', 'story_sandbox_selection_rewrite_done',
])
const ERROR_TYPES = new Set([
  'author_loop_error', 'setup_chat_error',
  'story_sandbox_error', 'story_sandbox_suggestions_regenerate_error',
  'story_sandbox_selection_rewrite_error',
])
const CANCEL_TYPES = new Set([
  'author_loop_stopped', 'setup_chat_turn_cancelled', 'story_sandbox_turn_cancelled',
])

interface NovelStatusState {
  byNovelId: Record<string, NovelRunStatus>
}

const initialState: NovelStatusState = { byNovelId: {} }

const novelStatusSlice = createSlice({
  name: 'novelStatus',
  initialState,
  reducers: {
    /** Seeds initial state from GET /api/novels/status on app mount -- lifecycle WS events
     * only carry future transitions, not what's already running when the page loads. */
    novelStatusSnapshotLoaded: (
      state,
      action: { payload: Record<string, { author_loop: boolean; setup_chat: boolean; story_sandbox: boolean }> },
    ) => {
      for (const [novelId, flags] of Object.entries(action.payload)) {
        if (flags.author_loop || flags.setup_chat || flags.story_sandbox) {
          state.byNovelId[novelId] = 'running'
        }
      }
    },
    /** Clears a 'done'/'error' novel back to idle -- called after the UI has shown the
     * flash long enough (see NovelRail's timeout) or once the user opens that novel. */
    novelStatusAcknowledged: (state, action: { payload: { novelId: string } }) => {
      delete state.byNovelId[action.payload.novelId]
    },
  },
  extraReducers: (builder) => {
    builder.addCase(wsEventReceived, (state, action) => {
      const { type, novel_id: novelId } = action.payload
      if (!novelId) return
      if (START_TYPES.has(type)) {
        state.byNovelId[novelId] = 'running'
      } else if (ERROR_TYPES.has(type)) {
        state.byNovelId[novelId] = 'error'
      } else if (DONE_TYPES.has(type)) {
        state.byNovelId[novelId] = 'done'
      } else if (CANCEL_TYPES.has(type)) {
        delete state.byNovelId[novelId]
      }
    })
  },
})

export const { novelStatusSnapshotLoaded, novelStatusAcknowledged } = novelStatusSlice.actions
export default novelStatusSlice.reducer

export const selectNovelRunStatus = (novelId: string) => (state: RootState): NovelRunStatus =>
  state.novelStatus.byNovelId[novelId] ?? 'idle'
