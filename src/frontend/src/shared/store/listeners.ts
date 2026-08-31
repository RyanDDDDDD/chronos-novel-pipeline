import { createListenerMiddleware, isAnyOf } from '@reduxjs/toolkit'
import { toast } from 'sonner'
import type { RootState, AppDispatch } from '@/shared/store/store'
import { wsEventReceived } from '@/shared/store/wsActions'
import { wsConnected } from '@/shared/store/connectionSlice'
import { fetchSetupChatStatus, fetchSetupChatMode, sendSetupChatMessage, setupChatDequeueAndStart, setupChatEventApplied, selectSetupChatCanDrainQueue } from '@/features/chat/store/setupChatSlice'
import {
  authorLoopRunBegin, authorLoopResumeBegin, authorLoopStalledSet,
  authorLoopLiveRunSet, authorLoopAutoSaveSettled, saveAuthorLoop, fetchAuthorLoopStatus,
} from '@/features/author/store/authorLoopSlice'
import { syncAuthorLoopForChapter } from '@/features/author/store/authorLoopSlice'
import { setChapter } from '@/shared/store/uiSlice'
import { loadNovelStatusSnapshot } from '@/shared/queries/novelStatusSnapshot'
import { queryClient } from '@/shared/lib/queryClient'
import { novitaModelCatalogKey, authorSceneImagesPrefixKey } from '@/shared/queries/keys'
import { cloudAuthErrorMessage } from '@/features/services/cloudAuthErrors'

// No event received within this long while running -> soft "suspected stuck" alarm (status
// itself doesn't change). Must exceed a single LLM call's backend timeout (120s) but there's a
// heartbeat before every attempt, so 75s reports early without false alarms.
const STALL_WARN_MS = 75_000

const AUTHOR_LOG_SKIP = new Set(['author_loop_segment', 'author_loop_progress'])

function authorLogPreview(data: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(data)) {
    out[k] = typeof v === 'string' && v.length > 120 ? `${v.slice(0, 120)}…(+${v.length - 120})` : v
  }
  return out
}

export const listenerMiddleware = createListenerMiddleware()
const startListening = listenerMiddleware.startListening.withTypes<RootState, AppDispatch>()

let lastAuthorEventTime = 0
let watchdogInterval: ReturnType<typeof setInterval> | null = null

// Console logging + watchdog "last event seen" bookkeeping for every author_loop_* WS event
// (live traffic AND journal-replay-via-hydrateAuthorLoop both flow through this same action).
startListening({
  actionCreator: wsEventReceived,
  effect: (action, listenerApi) => {
    const data = action.payload
    if (!data.type.startsWith('author_loop_')) return
    lastAuthorEventTime = Date.now()
    const log = AUTHOR_LOG_SKIP.has(data.type) ? console.debug : console.info
    log(`[主笔] ← ${data.type}`, authorLogPreview(data as unknown as Record<string, unknown>))

    const prevStatus = listenerApi.getOriginalState().authorLoop.status
    const curStatus = listenerApi.getState().authorLoop.status
    if (prevStatus === 'running' && (curStatus === 'idle' || curStatus === 'error')) {
      listenerApi.dispatch(authorLoopLiveRunSet(false))
    }
  },
})

// On the moment the WS connects, pull initial state that used to arrive only via REST polling
// (mirrors useOrchestrator.ts's `if (connected) { fetch... }` effect). novels/status is
// included so background-job toasts realign after a disconnect that missed *_done events.
startListening({
  actionCreator: wsConnected,
  effect: async (_action, listenerApi) => {
    listenerApi.dispatch(fetchAuthorLoopStatus())
    listenerApi.dispatch(fetchSetupChatStatus())
    listenerApi.dispatch(fetchSetupChatMode())
    await loadNovelStatusSnapshot(listenerApi.dispatch)
  },
})

// Whenever authorLoop.status settles into 'done' or 'idle' (from any action -- a WS event, a
// hydrate finishing, a reset...), refresh the resumable-chapters list. Using a predicate instead
// of matching specific actions because status can land on done/idle via several different paths.
startListening({
  predicate: (_action, currentState, previousState) => {
    const cur = (currentState as RootState).authorLoop.status
    const prev = (previousState as RootState).authorLoop.status
    return cur !== prev && (cur === 'done' || cur === 'idle')
  },
  effect: (_action, listenerApi) => {
    listenerApi.dispatch(fetchAuthorLoopStatus())
  },
})

// Watchdog: while a run is active, poll every 5s; flag stalled if no author_loop_* traffic for
// STALL_WARN_MS. Self-stops once status leaves 'running'.
startListening({
  matcher: isAnyOf(authorLoopRunBegin, authorLoopResumeBegin),
  effect: (_action, listenerApi) => {
    lastAuthorEventTime = Date.now()
    if (watchdogInterval !== null) clearInterval(watchdogInterval)
    watchdogInterval = setInterval(() => {
      if (listenerApi.getState().authorLoop.status !== 'running') {
        if (watchdogInterval !== null) clearInterval(watchdogInterval)
        watchdogInterval = null
        return
      }
      if (Date.now() - lastAuthorEventTime > STALL_WARN_MS) {
        listenerApi.dispatch(authorLoopStalledSet(true))
      }
    }, 5000)
  },
})

// Chapter picker (AuthorLoopPage/ChapterManuscriptPage/StorySandboxPage all dispatch setChapter)
// drives the idle-view hydrate/clear sync, decoupled from any one component's lifecycle.
startListening({
  actionCreator: setChapter,
  effect: (action, listenerApi) => {
    listenerApi.dispatch(syncAuthorLoopForChapter(action.payload))
  },
})

// resumableChapters can also change asynchronously (a status-settle refresh, a restart dropping
// the current chapter) while the user stays on the same chapter -- re-sync so a chapter that just
// became resumable picks up its journal without requiring the user to reselect it.
startListening({
  predicate: (_action, currentState, previousState) =>
    (currentState as RootState).authorLoop.resumableChapters !== (previousState as RootState).authorLoop.resumableChapters,
  effect: (_action, listenerApi) => {
    listenerApi.dispatch(syncAuthorLoopForChapter((listenerApi.getState() as RootState).ui.chapter))
  },
})

// Setup-chat "待发送" queue lives in Redux but must drain even when SetupChatPanel is unmounted
// (user switched to another tab while the agent is still working). Mirrors how wsEventReceived
// keeps folding setup_chat_* into chat state regardless of what's mounted.
startListening({
  predicate: (_action, currentState, previousState) => {
    const cur = selectSetupChatCanDrainQueue(currentState as RootState)
    const prev = selectSetupChatCanDrainQueue(previousState as RootState)
    return cur && !prev
  },
  effect: async (_action, listenerApi) => {
    const next = listenerApi.getState().setupChat.messageQueue[0]
    if (!next) return
    listenerApi.dispatch(setupChatDequeueAndStart())
    const result = await listenerApi.dispatch(
      sendSetupChatMessage({ text: next.text, attachmentIds: next.attachmentIds }),
    )
    if (sendSetupChatMessage.fulfilled.match(result) && !result.payload.ok) {
      listenerApi.dispatch(
        setupChatEventApplied({ type: 'setup_chat_error', error: result.payload.error ?? '发送失败' }),
      )
    }
  },
})

// A liveRun (user-initiated, not hydrate-replayed) chapter finishing triggers an automatic save;
// the outcome is stashed in authorLoop.lastAutoSave for App.tsx's toast effect (Task 12) to
// consume -- this listener only orchestrates the save call + state bookkeeping, no toast here.
startListening({
  actionCreator: wsEventReceived,
  effect: async (action, listenerApi) => {
    if (action.payload.type !== 'author_loop_done') return
    const state = listenerApi.getState()
    if (!state.authorLoop.liveRun) return
    listenerApi.dispatch(authorLoopLiveRunSet(false))
    const chapter = state.authorLoop.chapter
    const result = await listenerApi.dispatch(saveAuthorLoop(chapter))
    const payload = result.payload as { ok: boolean; path?: string; error?: string }
    listenerApi.dispatch(authorLoopAutoSaveSettled({ ok: payload.ok, chapter, error: payload.error }))
  },
})

// A finished portrait generation (success or failure) means the character's portrait_path may
// have changed -- refetch the cast list so CastCharacterGridCard picks up the new image.
startListening({
  actionCreator: wsEventReceived,
  effect: (action) => {
    if (action.payload.type !== 'portrait_generation_done') return
    void queryClient.invalidateQueries({ queryKey: ['setup', 'cast'] })
  },
})

startListening({
  actionCreator: wsEventReceived,
  effect: (action) => {
    if (action.payload.type !== 'novita_model_catalog_refreshed') return
    void queryClient.invalidateQueries({ queryKey: novitaModelCatalogKey })
  },
})

// A finished author scene-image generation (success only) means a new image landed on disk --
// refetch the per-chapter scene-image map so the manuscript view picks it up. Failures are left
// alone: authorSceneImageSlice already surfaces those via byKey/lastFailure.
startListening({
  actionCreator: wsEventReceived,
  effect: (action) => {
    if (action.payload.type !== 'author_scene_image_done') return
    if (action.payload.error) return
    void queryClient.invalidateQueries({ queryKey: authorSceneImagesPrefixKey })
  },
})

// Google login completes asynchronously after the browser round-trip, when the dialog is
// already closed; toast the outcome so a failure or success is never silent.
startListening({
  actionCreator: wsEventReceived,
  effect: (action) => {
    if (action.payload.type === 'cloud_auth_login_failed') {
      toast.error(cloudAuthErrorMessage(action.payload.error_code), { duration: 7000 })
    } else if (action.payload.type === 'cloud_auth_login_succeeded') {
      toast.success('已登录 Chronos 账号', { duration: 5000 })
    }
  },
})
