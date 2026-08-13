import { createSlice, type PayloadAction } from '@reduxjs/toolkit'
import type { RootState } from '@/shared/store/store'
import { resetForNovelSwitch } from '@/shared/store/resetForNovelSwitch'
import type { View } from '@/shared/utils/novelRoute'

interface UiState {
  chapter: number
  novelSwitchTarget: string | null
  novelSwitchResetting: boolean
}

const initialState: UiState = {
  chapter: 1,
  novelSwitchTarget: null,
  novelSwitchResetting: false,
}

const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    setChapter: (state, action: PayloadAction<number>) => { state.chapter = action.payload },
    clearNovelSwitchTarget: (state) => {
      state.novelSwitchTarget = null
      state.novelSwitchResetting = false
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(resetForNovelSwitch.pending, (state, action) => {
        state.novelSwitchTarget = action.meta.arg
        state.novelSwitchResetting = true
      })
      .addCase(resetForNovelSwitch.fulfilled, (state) => {
        state.novelSwitchResetting = false
      })
      .addCase(resetForNovelSwitch.rejected, (state) => {
        state.novelSwitchTarget = null
        state.novelSwitchResetting = false
      })
  },
})

export const { setChapter, clearNovelSwitchTarget } = uiSlice.actions
export const selectChapter = (state: RootState): number => state.ui.chapter
export const selectNovelSwitchTarget = (state: RootState): string | null => state.ui.novelSwitchTarget

/** Full-screen overlay while a novel switch is resetting per-novel agent state and (on chat/sandbox
 * views) the target novel's conversation history is still loading. */
export function selectNovelSwitchOverlayVisible(
  state: RootState,
  view: View,
  activeNovelId: string,
): boolean {
  const target = state.ui.novelSwitchTarget
  if (!target || target !== activeNovelId) return false
  if (state.ui.novelSwitchResetting) return true
  if (view === 'chat') {
    return (
      state.setupChat.hydrating
      || state.setupChat.historyLoadedNovel !== target
    )
  }
  if (view === 'sandbox') {
    return state.sandbox.hydrating
  }
  return false
}

export default uiSlice.reducer
