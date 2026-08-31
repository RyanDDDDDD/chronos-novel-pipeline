import { configureStore } from '@reduxjs/toolkit'
import connectionReducer from '@/shared/store/connectionSlice'
import novelImportReducer from '@/features/chat/store/novelImportSlice'
import tokenUsageReducer from '@/shared/store/tokenUsageSlice'
import setupChatReducer from '@/features/chat/store/setupChatSlice'
import authorLoopReducer from '@/features/author/store/authorLoopSlice'
import sandboxReducer from '@/features/sandbox/store/sandboxSlice'
import uiReducer from '@/shared/store/uiSlice'
import servicePingReducer from '@/shared/store/servicePingSlice'
import novelStatusReducer from '@/shared/store/novelStatusSlice'
import backgroundJobsReducer from '@/shared/store/backgroundJobsSlice'
import portraitGenerationReducer from '@/shared/store/portraitGenerationSlice'
import sandboxSceneImageReducer from '@/shared/store/sandboxSceneImageSlice'
import authorSceneImageReducer from '@/shared/store/authorSceneImageSlice'
import viewUnreadReducer from '@/shared/store/viewUnreadSlice'
import cloudAuthReducer from '@/features/services/store/cloudAuthSlice'
import { wsMiddleware } from '@/shared/store/wsMiddleware'
import { listenerMiddleware } from '@/shared/store/listeners'

export const store = configureStore({
  reducer: {
    connection: connectionReducer,
    novelImport: novelImportReducer,
    tokenUsage: tokenUsageReducer,
    setupChat: setupChatReducer,
    authorLoop: authorLoopReducer,
    sandbox: sandboxReducer,
    ui: uiReducer,
    servicePing: servicePingReducer,
    novelStatus: novelStatusReducer,
    backgroundJobs: backgroundJobsReducer,
    portraitGeneration: portraitGenerationReducer,
    sandboxSceneImage: sandboxSceneImageReducer,
    authorSceneImage: authorSceneImageReducer,
    viewUnread: viewUnreadReducer,
    cloudAuth: cloudAuthReducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware().prepend(listenerMiddleware.middleware).concat(wsMiddleware),
})

export type RootState = ReturnType<typeof store.getState>
export type AppDispatch = typeof store.dispatch
