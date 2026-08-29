import { createSlice } from '@reduxjs/toolkit'
import type { RootState } from '@/shared/store/store'
import { wsEventReceived } from '@/shared/store/wsActions'

type Status = 'generating' | 'failed'

interface State {
  // Keyed by `<chapter>:<branchId>:<roundId>` -- a scene image is scoped to one round of one
  // branch of one chapter, same key shape as the backend sidecar doc.
  byKey: Record<string, Status>
  // Consume-once slot for the panel's failure toast, mirrors portraitGenerationSlice.lastFailure
  // (the backend broadcast is already terminal, no intermediate retries reach here).
  lastFailure: { roundId: string; error: string } | null
}

const initialState: State = { byKey: {}, lastFailure: null }

const k = (chapter: number | string, branch: string, round: string) => `${chapter}:${branch}:${round}`

const slice = createSlice({
  name: 'sandboxSceneImage',
  initialState,
  reducers: {
    sandboxSceneImageFailureConsumed: (s) => { s.lastFailure = null },
  },
  extraReducers: (builder) => {
    builder.addCase(wsEventReceived, (s, a) => {
      const { type, chapter, branch_id: branch, round_id: round, error } = a.payload
      if (typeof chapter === 'undefined' || !branch || !round) return
      const key = k(chapter, branch, round)
      if (type === 'sandbox_scene_image_started') {
        s.byKey[key] = 'generating'
      } else if (type === 'sandbox_scene_image_done') {
        if (error) {
          s.byKey[key] = 'failed'
          s.lastFailure = { roundId: round, error }
        } else {
          delete s.byKey[key]
        }
      }
    })
  },
})

export const { sandboxSceneImageFailureConsumed } = slice.actions

export const selectSceneImageStatus = (
  st: RootState, chapter: number, branch: string, round: string,
): Status | undefined => st.sandboxSceneImage.byKey[k(chapter, branch, round)]

export const selectSceneImageLastFailure = (st: RootState) => st.sandboxSceneImage.lastFailure

export default slice.reducer
