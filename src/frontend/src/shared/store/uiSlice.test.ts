import { describe, it, expect } from 'vitest'
import { configureStore } from '@reduxjs/toolkit'
import uiReducer, { selectNovelSwitchOverlayVisible, selectNovelSwitchTarget } from '@/shared/store/uiSlice'
import setupChatReducer, {
  resetSetupChat, setupChatHydrateFinalized, selectSetupChatHistoryLoadedNovel,
} from '@/features/chat/store/setupChatSlice'
import sandboxReducer from '@/features/sandbox/store/sandboxSlice'
import { resetForNovelSwitch } from '@/shared/store/resetForNovelSwitch'
import authorLoopReducer from '@/features/author/store/authorLoopSlice'
import tokenUsageReducer from '@/shared/store/tokenUsageSlice'
import novelImportReducer from '@/features/chat/store/novelImportSlice'
import type { RootState } from '@/shared/store/store'

function buildStore() {
  return configureStore({
    reducer: {
      ui: uiReducer,
      setupChat: setupChatReducer,
      sandbox: sandboxReducer,
      authorLoop: authorLoopReducer,
      tokenUsage: tokenUsageReducer,
      novelImport: novelImportReducer,
    },
  })
}

describe('selectNovelSwitchOverlayVisible', () => {
  it('is true while resetForNovelSwitch is pending', () => {
    const store = buildStore()
    store.dispatch(resetForNovelSwitch.pending('', 'novel-b'))
    expect(selectNovelSwitchOverlayVisible(store.getState() as RootState, 'pipeline', 'novel-b')).toBe(true)
  })

  it('stays true on chat view until setup-chat history has loaded for the target novel', () => {
    const store = buildStore()
    store.dispatch(resetForNovelSwitch.pending('', 'novel-b'))
    store.dispatch(resetForNovelSwitch.fulfilled(undefined, '', 'novel-b'))
    expect(selectNovelSwitchOverlayVisible(store.getState() as RootState, 'chat', 'novel-b')).toBe(true)
  })

  it('is false on non-chat views once reset completes', () => {
    const store = buildStore()
    store.dispatch(resetForNovelSwitch.pending('', 'novel-b'))
    store.dispatch(resetForNovelSwitch.fulfilled(undefined, '', 'novel-b'))
    expect(selectNovelSwitchOverlayVisible(store.getState() as RootState, 'pipeline', 'novel-b')).toBe(false)
  })

  it('is false on chat view once setup-chat history has loaded for the target novel', () => {
    const store = buildStore()
    store.dispatch(resetForNovelSwitch.pending('', 'novel-b'))
    store.dispatch(resetForNovelSwitch.fulfilled(undefined, '', 'novel-b'))
    store.dispatch(resetSetupChat('novel-b'))
    store.dispatch(setupChatHydrateFinalized())
    expect(selectSetupChatHistoryLoadedNovel(store.getState() as RootState)).toBe('novel-b')
    expect(selectNovelSwitchOverlayVisible(store.getState() as RootState, 'chat', 'novel-b')).toBe(false)
  })
})
