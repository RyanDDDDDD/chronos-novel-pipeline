import React from 'react'
import { render, type RenderResult } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Provider } from 'react-redux'
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
import viewUnreadReducer from '@/shared/store/viewUnreadSlice'
import cloudAuthReducer from '@/features/services/store/cloudAuthSlice'
import { listenerMiddleware } from '@/shared/store/listeners'
import { authorLoopDialogueKey } from '@/shared/queries/keys'
import { TestProviders } from '@/test/testProviders'
import type { RootState } from '@/shared/store/store'

const EMPTY_DIALOGUE_CONFIG = {
  config: {
    target_words: 3000,
    disabled_buildtime_review_hooks: [],
    disabled_runtime_review_hooks: [],
    disabled_setup_review_hooks: [],
    llm_params: {},
    sandbox_llm_params: {},
    import_llm_params: {},
    auto_build_character_count: 5,
    auto_build_chapter_count: 3,
    chat_identity: '',
    portrait_style_prompt: '',
    portrait_negative_prompt: '',
    portrait_style_preset_id: 'anime',
  },
  default_identity: '',
  buildtime_review_hooks: [],
  runtime_review_hooks: [],
  setup_review_hooks: [],
}

/**
 *Rendering helper for testing: Each time you create a new QueryClient (turn off retry and staleTime to prevent the seed from being overwritten by background re-pull),
 *And seed ['novels'] on demand to let useActiveNovelId resolve to active novels, thus enabling per-novel query of enabled:!!novelId.
 */
export function renderWithClient(
  ui: React.ReactElement,
  { activeNovelId = 'default', seedDialogueConfig = false }: { activeNovelId?: string; seedDialogueConfig?: boolean } = {},
): RenderResult {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  if (activeNovelId) {
    client.setQueryData(['novels'], [{ id: activeNovelId, name: 'N', active: true }])
  }
  if (seedDialogueConfig) {
    client.setQueryData(authorLoopDialogueKey(activeNovelId), EMPTY_DIALOGUE_CONFIG)
  }
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <TestProviders>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </TestProviders>
  )
  return render(ui, { wrapper: Wrapper })
}

/** Builds an isolated Redux store with the same reducer/middleware shape as production
 * (minus wsMiddleware -- tests don't want a real WebSocket connecting), optionally
 * preloaded with partial state. */
export function buildTestStore(preloadedState?: Partial<RootState>) {
  return configureStore({
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
      viewUnread: viewUnreadReducer,
      cloudAuth: cloudAuthReducer,
    },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().prepend(listenerMiddleware.middleware),
    preloadedState: preloadedState as RootState | undefined,
  })
}

/** Same as renderWithClient, plus a Redux <Provider> -- the default for any component that
 * touches store state/dispatch (i.e. everything migrated off useOrchestrator props). */
export function renderWithProviders(
  ui: React.ReactElement,
  { activeNovelId = 'default', preloadedState }: { activeNovelId?: string; preloadedState?: Partial<RootState> } = {},
): RenderResult {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  if (activeNovelId) {
    client.setQueryData(['novels'], [{ id: activeNovelId, name: 'N', active: true }])
  }
  const store = buildTestStore(preloadedState)
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <TestProviders>
      <Provider store={store}>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </Provider>
    </TestProviders>
  )
  return render(ui, { wrapper: Wrapper })
}
