import { createSlice } from '@reduxjs/toolkit'
import type { RootState } from '@/shared/store/store'
import { wsEventReceived } from '@/shared/store/wsActions'

type PortraitStatus = 'generating' | 'failed'

interface PortraitGenerationState {
  byNovelId: Record<string, Record<string, PortraitStatus>>
  // Consume-once slot for App.tsx's toast effect (mirrors authorLoopSlice.lastAutoSave) --
  // the backend already retries internally before broadcasting `error`, so any error
  // reaching here is the terminal outcome, not an intermediate retry attempt.
  lastFailure: { character: string; error: string } | null
}

const initialState: PortraitGenerationState = { byNovelId: {}, lastFailure: null }

const portraitGenerationSlice = createSlice({
  name: 'portraitGeneration',
  initialState,
  reducers: {
    portraitGenerationFailureConsumed: (state) => { state.lastFailure = null },
  },
  extraReducers: (builder) => {
    builder.addCase(wsEventReceived, (state, action) => {
      const { type, novel_id: novelId, character, error } = action.payload
      if (!novelId || !character) return

      if (type === 'portrait_generation_started') {
        (state.byNovelId[novelId] ??= {})[character] = 'generating'
      } else if (type === 'portrait_generation_done') {
        const novelEntry = state.byNovelId[novelId]
        if (!novelEntry) return
        if (error) {
          novelEntry[character] = 'failed'
          state.lastFailure = { character, error }
        } else {
          delete novelEntry[character]
        }
      }
    })
  },
})

export default portraitGenerationSlice.reducer

export const { portraitGenerationFailureConsumed } = portraitGenerationSlice.actions

export const selectPortraitGenerating = (novelId: string, characterName: string) =>
  (state: RootState): 'idle' | PortraitStatus =>
    state.portraitGeneration.byNovelId[novelId]?.[characterName] ?? 'idle'

export const selectPortraitLastFailure = (state: RootState) => state.portraitGeneration.lastFailure
