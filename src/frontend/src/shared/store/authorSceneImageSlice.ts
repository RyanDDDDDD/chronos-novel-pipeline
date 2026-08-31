import { createSlice } from '@reduxjs/toolkit'
import type { RootState } from '@/shared/store/store'
import { wsEventReceived } from '@/shared/store/wsActions'

type Status = 'generating' | 'failed'

interface State {
  // Keyed by `<chapter>:<stageIndex>` -- one scene image per finalized stage of one chapter,
  // same key shape as the backend sidecar doc.
  byKey: Record<string, Status>
  // Consume-once slot for the page's failure toast (backend broadcast is already terminal).
  // Carries `chapter` so a page showing another chapter doesn't toast someone else's failure.
  lastFailure: { chapter: number; index: number; error: string } | null
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
      const { type, chapter, index, error, resume } = a.payload
      if (typeof chapter === 'undefined') return
      // A fresh start rewrites this chapter's stages from scratch, so last run's in-flight and
      // failed markers for it are stale. A resume keeps its stages (and any generation still
      // running against them), and other chapters are untouched either way.
      if (type === 'author_loop_start' && !resume) {
        const prefix = `${chapter}:`
        for (const key of Object.keys(s.byKey)) {
          if (key.startsWith(prefix)) delete s.byKey[key]
        }
        if (s.lastFailure?.chapter === chapter) s.lastFailure = null
        return
      }
      if (typeof index === 'undefined') return
      const key = k(chapter, index)
      if (type === 'author_scene_image_started') {
        s.byKey[key] = 'generating'
      } else if (type === 'author_scene_image_done') {
        if (error) {
          s.byKey[key] = 'failed'
          s.lastFailure = { chapter, index, error }
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
