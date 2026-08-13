import { createSlice, type PayloadAction } from '@reduxjs/toolkit'
import type { RootState } from '@/shared/store/store'
import { wsEventReceived } from '@/shared/store/wsActions'
import type { View } from '@/shared/utils/novelRoute'
import {
  clearViewUnread, EMPTY_VIEW_UNREAD, isNotifyView, markViewUnread, viewForWsEventType,
  type ViewUnreadState,
} from '@/shared/utils/viewUnreadBadges'

interface ViewUnreadSliceState {
  byNovelId: Record<string, ViewUnreadState>
  focusNovelId: string | null
  focusView: View | null
  focusIsArchives: boolean
}

const initialState: ViewUnreadSliceState = {
  byNovelId: {},
  focusNovelId: null,
  focusView: null,
  focusIsArchives: false,
}

const viewUnreadSlice = createSlice({
  name: 'viewUnread',
  initialState,
  reducers: {
    /** Fired on every route/tab change (including a novel switch) -- records what the user is
     * now looking at, and clears that (novel, tab)'s own badge since they're looking right at it. */
    viewFocusChanged: (
      state,
      action: PayloadAction<{ novelId: string; view: View; isArchives: boolean }>,
    ) => {
      const { novelId, view, isArchives } = action.payload
      state.focusNovelId = novelId
      state.focusView = view
      state.focusIsArchives = isArchives
      const prev = state.byNovelId[novelId]
      if (!prev) return
      let next = prev
      if (isArchives) next = clearViewUnread(next, 'archives')
      if (isNotifyView(view)) next = clearViewUnread(next, view)
      if (next !== prev) state.byNovelId[novelId] = next
    },
  },
  extraReducers: (builder) => {
    builder.addCase(wsEventReceived, (state, action) => {
      const { type, novel_id: novelId } = action.payload
      if (!novelId) return
      const prev = state.byNovelId[novelId] ?? EMPTY_VIEW_UNREAD
      const isFocusedNovel = novelId === state.focusNovelId
      if (isFocusedNovel && state.focusView) {
        const next = markViewUnread(prev, type, state.focusView, state.focusIsArchives)
        if (next !== prev) state.byNovelId[novelId] = next
        return
      }
      // Not the novel currently in view -- no tab can "already be on screen" for it, so any
      // matching event always marks unread (this is what fixes A's badge leaking onto B).
      const target = viewForWsEventType(type)
      if (!target || prev[target]) return
      state.byNovelId[novelId] = { ...prev, [target]: true }
    })
  },
})

export const { viewFocusChanged } = viewUnreadSlice.actions
export default viewUnreadSlice.reducer

export const selectViewUnreadForNovel = (novelId: string) => (state: RootState): ViewUnreadState =>
  state.viewUnread.byNovelId[novelId] ?? EMPTY_VIEW_UNREAD
