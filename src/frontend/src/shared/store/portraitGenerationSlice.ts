import { createSlice } from '@reduxjs/toolkit'
import type { RootState } from '@/shared/store/store'
import { wsEventReceived } from '@/shared/store/wsActions'

type PortraitStatus = 'generating' | 'failed'

interface PortraitGenerationState {
  byNovelId: Record<string, Record<string, PortraitStatus>>
}

const initialState: PortraitGenerationState = { byNovelId: {} }

const portraitGenerationSlice = createSlice({
  name: 'portraitGeneration',
  initialState,
  reducers: {},
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
        } else {
          delete novelEntry[character]
        }
      }
    })
  },
})

export default portraitGenerationSlice.reducer

export const selectPortraitGenerating = (novelId: string, characterName: string) =>
  (state: RootState): 'idle' | PortraitStatus =>
    state.portraitGeneration.byNovelId[novelId]?.[characterName] ?? 'idle'
