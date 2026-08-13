import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import type { AuthorLoopState, AuthorMessage } from '@/shared/types'
import type { RootState } from '@/shared/store/store'
import { setChapter as setChapterAction } from '@/shared/store/uiSlice'
import { wsEventReceived, type OrchestratorEvent } from '@/shared/store/wsActions'

interface AuthorLoopSliceState extends AuthorLoopState {
  resumableChapters: number[]
  hydratedChapter: number | null
  hydrateEpoch: number
  liveRun: boolean
  /** Set by the Task 9 listener once a liveRun chapter's author_loop_done triggers the
   * auto-save orchestration; consumed (cleared) by App.tsx's toast effect. null = nothing
   * pending. */
  lastAutoSave: { ok: boolean; chapter: number; error?: string } | null
}

const initialState: AuthorLoopSliceState = {
  status: 'idle', chapter: 0, total: 0, messages: [],
  resumableChapters: [], hydratedChapter: null, hydrateEpoch: 0, liveRun: false, lastAutoSave: null,
}

/** Sync chapter from WS payloads that carry an explicit chapter (reconnect replay, done, etc.). */
function syncChapterFromEvent(state: AuthorLoopSliceState, chapter: number | undefined) {
  if (chapter != null && chapter > 0) state.chapter = chapter
}

const authorLoopSlice = createSlice({
  name: 'authorLoop',
  initialState,
  reducers: {
    resetAuthorLoop: (state) => {
      state.hydrateEpoch += 1
      state.hydratedChapter = null
      state.status = 'idle'; state.chapter = 0; state.total = 0; state.messages = []
      state.chapterProgress = undefined; state.live = undefined
      state.progress = undefined; state.stalled = undefined; state.error = undefined
      state.styleRewriting = null
    },
    authorLoopChapterCleared: (state, action: { payload: number }) => {
      state.hydrateEpoch += 1
      state.hydratedChapter = null
      const chapter = action.payload
      if (state.chapter === chapter && state.messages.length === 0 && !state.chapterProgress) return
      state.status = 'idle'; state.chapter = chapter; state.total = 0; state.messages = []
      state.chapterProgress = null; state.live = null; state.progress = null
      state.styleRewriting = null
    },
    authorLoopHydrateBegin: (state, action: { payload: number }) => { state.hydratedChapter = action.payload },
    authorLoopHydrateCleared: (state, action: { payload: { chapter: number } }) => {
      state.status = 'idle'; state.chapter = action.payload.chapter; state.total = 0; state.messages = []
      state.chapterProgress = null; state.live = null; state.progress = null
      state.styleRewriting = null
    },
    authorLoopHydrateAbort: (state) => { state.hydratedChapter = null },
    authorLoopHydrateFinalized: () => {
      // No longer forces status/live/progress to idle -- journal_events() only omits the
      // synthetic author_loop_stopped marker (and appends the live tail instead) when this
      // chapter is genuinely still running, in which case the replay above already landed on
      // 'running' with live/progress correctly populated, exactly as real-time WS traffic would.
      // A genuinely paused/interrupted chapter's replay ends on a real or synthetic
      // author_loop_stopped event, whose own reducer case already sets status/live/styleRewriting
      // to idle/null -- nothing left for this action to force.
    },
    authorLoopRunBegin: (state, action: { payload: number }) => {
      state.status = 'running'; state.chapter = action.payload; state.total = 0; state.messages = []
    },
    authorLoopRunFailed: (state, action: { payload: { chapter: number; error: string } }) => {
      state.status = 'error'; state.chapter = action.payload.chapter
      state.total = 0; state.messages = []; state.error = action.payload.error
    },
    authorLoopResumeBegin: (state, action: { payload: number }) => {
      state.status = 'running'; state.chapter = action.payload; state.stalled = false
    },
    authorLoopResumeFailed: (state, action: { payload: string }) => {
      state.status = 'error'; state.error = action.payload
    },
    authorLoopResumableRemoved: (state, action: { payload: number }) => {
      state.resumableChapters = state.resumableChapters.filter((ch) => ch !== action.payload)
    },
    authorLoopLiveRunSet: (state, action: { payload: boolean }) => { state.liveRun = action.payload },
    authorLoopStalledSet: (state, action: { payload: boolean }) => { state.stalled = action.payload },
    authorLoopAutoSaveSettled: (state, action: { payload: { ok: boolean; chapter: number; error?: string } }) => {
      state.lastAutoSave = action.payload
    },
    authorLoopAutoSaveConsumed: (state) => { state.lastAutoSave = null },
  },
  extraReducers: (builder) => {
    builder
      .addCase(wsEventReceived, (state, action) => {
        const data = action.payload
        if (!data.type.startsWith('author_loop_')) return
        if (state.stalled) state.stalled = false // any live signal clears the "suspected stuck" alarm

        switch (data.type) {
          case 'author_loop_start':
            syncChapterFromEvent(state, data.chapter)
            if (data.resume) {
              state.status = 'running'; state.stalled = false
            } else {
              state.status = 'running'; state.total = 0
              state.messages = []; state.chapterProgress = null
            }
            break

          case 'author_loop_chapter_progress':
            syncChapterFromEvent(state, data.chapter)
            state.status = 'running'
            state.chapterProgress = { done: data.done ?? 0, total: data.total ?? 0 }
            break

          case 'author_loop_segment': {
            const segId = data.agent != null
              ? `seg-${data.index ?? 0}-agent-${data.agent}${data.role ? `-${data.role}` : ''}`
              : data.beat != null
                ? `seg-${data.index ?? 0}-beat-${data.beat}`
                : `seg-${data.index ?? 0}`
            const segMsg: AuthorMessage = {
              id: segId, role: 'agent', type: 'segment',
              segment: {
                index: data.index ?? 0, beat: data.beat ?? undefined, beats: data.beats ?? undefined,
                intent: data.intent ?? '', psychology: data.psychology ?? '', skill: data.skill ?? null,
                text: data.text ?? '', draft: data.draft === true, agent: data.agent, role: data.role,
              },
            }
            state.status = 'running'
            state.total = data.total ?? state.total
            state.live = null
            const idx = state.messages.findIndex((m) => m.id === segMsg.id)
            if (idx >= 0) state.messages[idx] = segMsg
            else state.messages.push(segMsg)
            break
          }

          case 'author_loop_state': {
            const stMsg: AuthorMessage = {
              id: `seg-${data.index ?? 0}-state`, role: 'agent', type: 'state',
              entry: data.entry === true,
              characters: ((data.characters as Record<string, unknown>[]) ?? []).map((c) => ({
                name: (c.name as string) ?? '', psychology: (c.psychology as string) ?? '',
                posture: (c.posture as string) ?? '', clothing: (c.clothing as string) ?? '',
                action: (c.action as string) ?? '', demeanor: (c.demeanor as string) ?? '',
              })),
            }
            state.status = 'running'; state.live = null
            const idx = state.messages.findIndex((m) => m.id === stMsg.id)
            if (idx >= 0) state.messages[idx] = stMsg
            else state.messages.push(stMsg)
            break
          }

          case 'author_loop_summary': {
            const suMsg: AuthorMessage = {
              id: `seg-${data.index ?? 0}-summary`, role: 'agent', type: 'summary', text: data.text ?? '',
            }
            state.status = 'running'; state.live = null
            const idx = state.messages.findIndex((m) => m.id === suMsg.id)
            if (idx >= 0) state.messages[idx] = suMsg
            else state.messages.push(suMsg)
            break
          }

          case 'author_loop_event_log': {
            const raw = data as OrchestratorEvent & {
              entries?: { summary?: string; time?: string; location?: string; characters?: string[] }[]
              event?: { summary?: string; time?: string; location?: string; characters?: string[] }
            }
            const entries = Array.isArray(raw.entries)
              ? raw.entries
                  .filter((e) => Boolean(e?.summary))
                  .map((e) => ({
                    summary: e?.summary ?? '', time: e?.time ?? '',
                    location: e?.location, characters: e?.characters,
                  }))
              : raw.event?.summary
                ? [{
                    summary: raw.event.summary ?? '', time: raw.event.time ?? '',
                    location: raw.event.location, characters: raw.event.characters,
                  }]
                : []
            const elMsg: AuthorMessage = {
              id: `seg-${data.index ?? 0}-event_log`, role: 'agent', type: 'event_log',
              events: entries,
            }
            const elIdx = state.messages.findIndex((m) => m.id === elMsg.id)
            if (elIdx >= 0) state.messages[elIdx] = elMsg
            else state.messages.push(elMsg)
            break
          }

          case 'author_loop_recall': {
            const rcMsg: AuthorMessage = {
              id: `seg-${data.index ?? 0}-recall`, role: 'agent', type: 'recall',
              recallContext: data.recall_context ?? '',
            }
            const rcIdx = state.messages.findIndex((m) => m.id === rcMsg.id)
            if (rcIdx >= 0) state.messages[rcIdx] = rcMsg
            else state.messages.push(rcMsg)
            break
          }

          case 'author_loop_token': {
            const agent = data.agent ?? ''
            const role = data.role
            const delta = data.delta ?? ''
            const live = state.live ?? []
            const last = live[live.length - 1]
            state.status = 'running'
            state.live = last && last.agent === agent && last.role === role
              ? [...live.slice(0, -1), { agent, role, text: last.text + delta }]
              : [...live, { agent, role, text: delta }]
            break
          }

          case 'author_loop_style_rewrite': {
            const rewriteStatus = (data as OrchestratorEvent & { status?: string }).status
            const agent = data.agent ?? ''
            const role = data.role ?? undefined
            if (rewriteStatus === 'start') {
              state.styleRewriting = { agent, role }
            } else if (rewriteStatus === 'end') {
              const current = state.styleRewriting
              if (current && current.agent === agent && current.role === role) {
                state.styleRewriting = null
              }
            }
            break
          }

          case 'author_loop_progress':
            state.status = 'running'
            state.progress = { agent: data.agent ?? '', attempt: data.attempt ?? 1, attempts: data.attempts ?? 1 }
            break

          case 'author_loop_done':
            syncChapterFromEvent(state, data.chapter)
            state.status = state.status === 'error' ? 'error' : 'done'
            if (state.chapterProgress && state.chapterProgress.total > 0) {
              state.chapterProgress = {
                done: state.chapterProgress.total,
                total: state.chapterProgress.total,
              }
            }
            state.progress = null; state.live = null; state.styleRewriting = null
            break

          case 'author_loop_error':
            syncChapterFromEvent(state, data.chapter)
            state.status = 'error'; state.live = null; state.styleRewriting = null
            state.error = data.error ?? '主笔写作失败'
            break

          case 'author_loop_stopped':
            syncChapterFromEvent(state, data.chapter)
            state.status = 'idle'; state.live = null; state.styleRewriting = null
            break

          default:
            break
        }
      })
      .addCase(fetchAuthorLoopStatus.fulfilled, (state, action) => {
        if (action.payload !== undefined) state.resumableChapters = action.payload
      })
  },
})

export const {
  resetAuthorLoop, authorLoopChapterCleared, authorLoopHydrateBegin, authorLoopHydrateCleared,
  authorLoopHydrateAbort, authorLoopHydrateFinalized, authorLoopRunBegin, authorLoopRunFailed,
  authorLoopResumeBegin, authorLoopResumeFailed, authorLoopResumableRemoved,
  authorLoopLiveRunSet, authorLoopStalledSet, authorLoopAutoSaveSettled, authorLoopAutoSaveConsumed,
} = authorLoopSlice.actions

export const fetchAuthorLoopStatus = createAsyncThunk(
  'authorLoop/fetchStatus',
  async (novelId: string | undefined, { dispatch }): Promise<number[] | undefined> => {
    try {
      const qs = novelId ? `?novel_id=${encodeURIComponent(novelId)}` : ''
      const res = await fetch(`/api/author-loop/status${qs}`)
      const body = await res.json().catch(() => ({}))
      const resumable = Array.isArray(body.resumable) ? body.resumable : []
      const runningChapter = typeof body.running_chapter === 'number' ? body.running_chapter : null
      if (runningChapter != null) {
        dispatch(setChapterAction(runningChapter))
        void dispatch(hydrateAuthorLoop({ chapter: runningChapter, novelId }))
      }
      return resumable
    } catch {
      return undefined
    }
  },
)

export const hydrateAuthorLoop = createAsyncThunk(
  'authorLoop/hydrate',
  async ({ chapter, novelId }: { chapter: number; novelId?: string }, { dispatch, getState }) => {
    const read = () => (getState() as RootState).authorLoop
    if (chapter < 1 || read().hydratedChapter === chapter) return
    const epoch = read().hydrateEpoch
    dispatch(authorLoopHydrateBegin(chapter))
    try {
      const qs = novelId ? `&novel_id=${encodeURIComponent(novelId)}` : ''
      const res = await fetch(`/api/author-loop/journal?chapter=${chapter}${qs}`)
      if (read().hydrateEpoch !== epoch) { dispatch(authorLoopHydrateAbort()); return }
      const body = await res.json().catch(() => ({}))
      const events: OrchestratorEvent[] = Array.isArray(body.events) ? body.events : []
      if (events.length === 0) {
        dispatch(authorLoopHydrateAbort())
        dispatch(authorLoopHydrateCleared({ chapter }))
        return
      }
      dispatch(authorLoopHydrateCleared({ chapter }))
      for (const ev of events) {
        if (read().hydrateEpoch !== epoch) { dispatch(authorLoopHydrateAbort()); return }
        dispatch(wsEventReceived(ev))
      }
      if (read().hydrateEpoch !== epoch) { dispatch(authorLoopHydrateAbort()); return }
      dispatch(authorLoopHydrateFinalized())
    } catch {
      dispatch(authorLoopHydrateAbort())
    }
  },
)

export const syncAuthorLoopForChapter = createAsyncThunk(
  'authorLoop/syncForChapter',
  (chapter: number, { dispatch, getState }) => {
    const s = (getState() as RootState).authorLoop
    if (s.status !== 'idle') return
    if (!s.resumableChapters.includes(chapter)) {
      dispatch(authorLoopChapterCleared(chapter))
      return
    }
    if (s.hydratedChapter === chapter) return
    void dispatch(hydrateAuthorLoop({ chapter }))
  },
)

export const startAuthorLoop = createAsyncThunk(
  'authorLoop/start',
  async (chapter: number, { dispatch }): Promise<{ ok: boolean; error?: string }> => {
    dispatch(authorLoopRunBegin(chapter))
    try {
      const res = await fetch('/api/author-loop/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ chapter }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok || body.ok === false) {
        const err = body.error ?? `启动失败 (HTTP ${res.status})`
        dispatch(authorLoopRunFailed({ chapter, error: err }))
        return { ok: false, error: err }
      }
      dispatch(authorLoopLiveRunSet(true))
      return { ok: true }
    } catch {
      const err = '无法连接后端'
      dispatch(authorLoopRunFailed({ chapter, error: err }))
      return { ok: false, error: err }
    }
  },
)

export const resumeAuthorLoop = createAsyncThunk(
  'authorLoop/resume',
  async (chapter: number, { dispatch }): Promise<{ ok: boolean; error?: string }> => {
    dispatch(authorLoopResumeBegin(chapter))
    try {
      const res = await fetch('/api/author-loop/resume', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ chapter }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok || body.ok === false) {
        const err = body.error ?? `续跑失败 (HTTP ${res.status})`
        dispatch(authorLoopResumeFailed(err))
        return { ok: false, error: err }
      }
      dispatch(authorLoopLiveRunSet(true))
      return { ok: true }
    } catch {
      const err = '无法连接后端'
      dispatch(authorLoopResumeFailed(err))
      return { ok: false, error: err }
    }
  },
)

export const restartAuthorLoop = createAsyncThunk(
  'authorLoop/restart',
  async (chapter: number, { dispatch }): Promise<{ ok: boolean; error?: string }> => {
    dispatch(authorLoopRunBegin(chapter))
    try {
      const res = await fetch('/api/author-loop/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chapter, fresh: true }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok || body.ok === false) {
        const err = body.error ?? `启动失败 (HTTP ${res.status})`
        dispatch(authorLoopRunFailed({ chapter, error: err }))
        return { ok: false, error: err }
      }
      dispatch(authorLoopResumableRemoved(chapter))
      dispatch(authorLoopLiveRunSet(true))
      return { ok: true }
    } catch {
      const err = '无法连接后端'
      dispatch(authorLoopRunFailed({ chapter, error: err }))
      return { ok: false, error: err }
    }
  },
)

export const stopAuthorLoop = createAsyncThunk('authorLoop/stop', async (): Promise<void> => {
  await fetch('/api/author-loop/stop', { method: 'POST' }).catch(() => {})
})

export const saveAuthorLoop = createAsyncThunk(
  'authorLoop/save',
  async (chapter: number): Promise<{ ok: boolean; path?: string; error?: string }> => {
    try {
      const res = await fetch('/api/author-loop/save', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ chapter }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok || body.ok === false) {
        return { ok: false, error: body.error ?? `保存失败 (HTTP ${res.status})` }
      }
      return { ok: true, path: body.path }
    } catch {
      return { ok: false, error: '无法连接后端' }
    }
  },
)

export const selectAuthorLoop = (state: RootState): AuthorLoopState => state.authorLoop
export const selectResumableChapters = (state: RootState): number[] => state.authorLoop.resumableChapters
export const selectAuthorLoopLiveRun = (state: RootState): boolean => state.authorLoop.liveRun
export const selectAuthorLoopLastAutoSave = (state: RootState): { ok: boolean; chapter: number; error?: string } | null =>
  state.authorLoop.lastAutoSave
export default authorLoopSlice.reducer
