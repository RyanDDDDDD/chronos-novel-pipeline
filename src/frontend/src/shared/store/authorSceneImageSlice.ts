import { createSlice } from '@reduxjs/toolkit'
import type { RootState } from '@/shared/store/store'
import { wsEventReceived } from '@/shared/store/wsActions'

type Status = 'generating' | 'failed'

interface State {
  // Keyed by `<chapter>:<stageIndex>` -- one scene image per finalized stage of one chapter,
  // same key shape as the backend sidecar doc.
  byKey: Record<string, Status>
  // Consume-once slot for the page's failure toast (backend broadcast is already terminal).
  lastFailure: { index: number; error: string } | null
}

const initialState: State = { byKey: {}, lastFailure: null }

const k = (chapter: number | string, index: number | string) => `${chapter}:${index}`

const slice = createSlice({
  name: 'authorSceneImage',
  initialState,
  reducers: {
    authorSceneImageFailureConsumed: (s) => { s.lastFailure = null },
  },
  extraReducers: (builder) => {
    builder.addCase(wsEventReceived, (s, a) => {
      const { type, chapter, index, error } = a.payload
      if (typeof chapter === 'undefined' || typeof index === 'undefined') return
      const key = k(chapter, index)
      if (type === 'author_scene_image_started') {
        s.byKey[key] = 'generating'
      } else if (type === 'author_scene_image_done') {
        if (error) {
          s.byKey[key] = 'failed'
          s.lastFailure = { index, error }
        } else {
          delete s.byKey[key]
        }
      }
    })
  },
})

export const { authorSceneImageFailureConsumed } = slice.actions

export const selectAuthorSceneImageStatus = (
  st: RootState, chapter: number, index: number,
): Status | undefined => st.authorSceneImage.byKey[k(chapter, index)]

export const selectAuthorSceneImageLastFailure = (st: RootState) => st.authorSceneImage.lastFailure

export default slice.reducer
