import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { configureStore } from '@reduxjs/toolkit'
import authorLoopReducer, {
  resetAuthorLoop, authorLoopLiveRunSet, authorLoopStalledSet,
  authorLoopAutoSaveSettled, authorLoopAutoSaveConsumed,
  startAuthorLoop, resumeAuthorLoop, restartAuthorLoop, stopAuthorLoop, saveAuthorLoop,
  fetchAuthorLoopStatus, hydrateAuthorLoop, syncAuthorLoopForChapter,
  selectAuthorLoop, selectResumableChapters, selectAuthorLoopLiveRun,
} from '@/features/author/store/authorLoopSlice'
import uiReducer from '@/shared/store/uiSlice'
import { wsEventReceived } from '@/shared/store/wsActions'

function buildStore(preloaded?: Partial<ReturnType<typeof authorLoopReducer>>) {
  return configureStore({
    reducer: { authorLoop: authorLoopReducer, ui: uiReducer },
    preloadedState: preloaded ? { authorLoop: { ...authorLoopReducer(undefined, { type: '@@INIT' }), ...preloaded } } : undefined,
  })
}

describe('authorLoopSlice reducer: WS events', () => {
  it('author_loop_start (fresh) resets messages/total and enters running', () => {
    const state = authorLoopReducer(
      { status: 'idle', chapter: 0, total: 5, messages: [{ id: 'x' }] as never, resumableChapters: [], hydratedChapter: null, hydrateEpoch: 0, liveRun: false, lastAutoSave: null },
      wsEventReceived({ type: 'author_loop_start', chapter: 3 }),
    )
    expect(state).toMatchObject({ status: 'running', chapter: 3, total: 0, messages: [] })
  })

  it('author_loop_start (resume) keeps messages/total, clears stalled', () => {
    const prev = { status: 'idle' as const, chapter: 3, total: 5, messages: [{ id: 'x' }] as never, resumableChapters: [], hydratedChapter: null, hydrateEpoch: 0, liveRun: false, lastAutoSave: null, stalled: true }
    const state = authorLoopReducer(prev, wsEventReceived({ type: 'author_loop_start', chapter: 3, resume: true }))
    expect(state.status).toBe('running')
    expect(state.total).toBe(5)
    expect(state.messages).toHaveLength(1)
    expect(state.stalled).toBe(false)
  })

  it('author_loop_segment appends a new segment message, updates in place on repeat id', () => {
    let state = authorLoopReducer(undefined, wsEventReceived({
      type: 'author_loop_segment', index: 0, beat: 0, intent: 'i', text: 'draft', draft: true, total: 1,
    }))
    expect(state.messages).toHaveLength(1)
    expect(state.messages[0]).toMatchObject({ id: 'seg-0-beat-0', type: 'segment' })
    state = authorLoopReducer(state, wsEventReceived({
      type: 'author_loop_segment', index: 0, beat: 0, intent: 'i', text: 'final', draft: false, total: 1,
    }))
    expect(state.messages).toHaveLength(1)
    expect((state.messages[0] as { segment: { text: string } }).segment.text).toBe('final')
  })

  it('author_loop_token accumulates deltas into the live bubble, splits on agent/role change', () => {
    let state = authorLoopReducer(undefined, wsEventReceived({ type: 'author_loop_token', agent: 'director', delta: 'A' }))
    state = authorLoopReducer(state, wsEventReceived({ type: 'author_loop_token', agent: 'director', delta: 'B' }))
    expect(state.live).toEqual([{ agent: 'director', role: undefined, text: 'AB' }])
    state = authorLoopReducer(state, wsEventReceived({ type: 'author_loop_token', agent: 'character', role: '甲', delta: 'C' }))
    expect(state.live).toEqual([
      { agent: 'director', role: undefined, text: 'AB' },
      { agent: 'character', role: '甲', text: 'C' },
    ])
  })

  it('author_loop_done goes to done unless already errored, clears progress/live', () => {
    const running = { status: 'running' as const, chapter: 1, total: 1, messages: [], resumableChapters: [], hydratedChapter: null, hydrateEpoch: 0, liveRun: false, lastAutoSave: null, live: [{ agent: 'x', text: 't' }] }
    expect(authorLoopReducer(running, wsEventReceived({ type: 'author_loop_done' })).status).toBe('done')
    const errored = { ...running, status: 'error' as const }
    expect(authorLoopReducer(errored, wsEventReceived({ type: 'author_loop_done' })).status).toBe('error')
  })

  it('author_loop_done syncs chapter from payload and finalizes chapterProgress to 100%', () => {
    const running = {
      status: 'running' as const, chapter: 0, total: 0, messages: [], resumableChapters: [],
      hydratedChapter: null, hydrateEpoch: 0, liveRun: false, lastAutoSave: null,
      chapterProgress: { done: 2, total: 3 },
    }
    const state = authorLoopReducer(
      running,
      wsEventReceived({ type: 'author_loop_done', chapter: 5 }),
    )
    expect(state.chapter).toBe(5)
    expect(state.chapterProgress).toEqual({ done: 3, total: 3 })
    expect(state.status).toBe('done')
  })

  it('author_loop_chapter_progress syncs chapter from payload on reconnect replay', () => {
    const idle = {
      status: 'idle' as const, chapter: 0, total: 0, messages: [], resumableChapters: [],
      hydratedChapter: null, hydrateEpoch: 0, liveRun: false, lastAutoSave: null,
    }
    const state = authorLoopReducer(
      idle,
      wsEventReceived({ type: 'author_loop_chapter_progress', chapter: 4, done: 2, total: 5 }),
    )
    expect(state.chapter).toBe(4)
    expect(state.chapterProgress).toEqual({ done: 2, total: 5 })
    expect(state.status).toBe('running')
  })

  it('author_loop_error sets status=error and records the message', () => {
    const state = authorLoopReducer(undefined, wsEventReceived({ type: 'author_loop_error', error: '写崩了' }))
    expect(state.status).toBe('error')
    expect(state.error).toBe('写崩了')
  })

  it('any author_loop_* event clears a stale stalled flag', () => {
    const prev = { status: 'running' as const, chapter: 1, total: 1, messages: [], resumableChapters: [], hydratedChapter: null, hydrateEpoch: 0, liveRun: false, lastAutoSave: null, stalled: true }
    const state = authorLoopReducer(prev, wsEventReceived({ type: 'author_loop_progress', agent: 'write', attempt: 1, attempts: 1 }))
    expect(state.stalled).toBe(false)
  })

  it('author_loop_event_log appends an event_log message, updates in place on repeat id', () => {
    let state = authorLoopReducer(undefined, wsEventReceived({
      type: 'author_loop_event_log', index: 0,
      entries: [{ summary: '阿明推开门', time: '深夜', location: '书房', characters: ['阿明'] }],
    } as never))
    expect(state.messages).toHaveLength(1)
    expect(state.messages[0]).toMatchObject({ id: 'seg-0-event_log', type: 'event_log' })
    expect((state.messages[0] as { events: { summary: string }[] }).events[0].summary).toBe('阿明推开门')
    state = authorLoopReducer(state, wsEventReceived({
      type: 'author_loop_event_log', index: 0,
      entries: [
        { summary: '阿明推开门', time: '深夜', location: '书房', characters: ['阿明'] },
        { summary: '乙想起往事', time: '童年', location: '', characters: ['乙'] },
      ],
    } as never))
    expect(state.messages).toHaveLength(1)
    expect((state.messages[0] as { events: { summary: string }[] }).events).toHaveLength(2)
  })

  it('author_loop_event_log accepts legacy singular event field', () => {
    const state = authorLoopReducer(undefined, wsEventReceived({
      type: 'author_loop_event_log', index: 0,
      event: { summary: '旧协议', time: '上午' },
    } as never))
    expect((state.messages[0] as { events: { summary: string }[] }).events[0].summary).toBe('旧协议')
  })

  it('author_loop_recall appends a recall message even when recall_context is empty', () => {
    const state = authorLoopReducer(undefined, wsEventReceived({
      type: 'author_loop_recall', index: 0, recall_context: '',
    } as never))
    expect(state.messages).toHaveLength(1)
    expect(state.messages[0]).toMatchObject({ id: 'seg-0-recall', type: 'recall', recallContext: '' })
  })

  it('non author_loop_ events are ignored', () => {
    const prev = authorLoopReducer(undefined, { type: '@@INIT' })
    expect(authorLoopReducer(prev, wsEventReceived({ type: 'archive_build_start' }))).toBe(prev)
  })

  it('author_loop_style_rewrite start sets styleRewriting', () => {
    const state = authorLoopReducer(
      undefined,
      wsEventReceived({ type: 'author_loop_style_rewrite', status: 'start', agent: 'narration' } as never),
    )
    expect(state.styleRewriting).toEqual({ agent: 'narration', role: undefined })
  })

  it('author_loop_style_rewrite end clears styleRewriting when agent matches', () => {
    const prev = {
      status: 'running' as const, chapter: 1, total: 1, messages: [], resumableChapters: [], hydratedChapter: null,
      hydrateEpoch: 0, liveRun: false, lastAutoSave: null,
      styleRewriting: { agent: 'narration', role: undefined },
    }
    const state = authorLoopReducer(
      prev,
      wsEventReceived({ type: 'author_loop_style_rewrite', status: 'end', agent: 'narration' } as never),
    )
    expect(state.styleRewriting).toBeNull()
  })

  it('author_loop_style_rewrite normalizes role null to undefined on start and end', () => {
    const started = authorLoopReducer(
      undefined,
      wsEventReceived({ type: 'author_loop_style_rewrite', status: 'start', agent: 'narration', role: null } as never),
    )
    expect(started.styleRewriting).toEqual({ agent: 'narration', role: undefined })
    expect(started.styleRewriting?.role).not.toBeNull()

    const cleared = authorLoopReducer(
      started,
      wsEventReceived({ type: 'author_loop_style_rewrite', status: 'end', agent: 'narration', role: null } as never),
    )
    expect(cleared.styleRewriting).toBeNull()
  })

  it('author_loop_done/error/stopped clear styleRewriting as safety net', () => {
    const base = {
      status: 'running' as const, chapter: 1, total: 1, messages: [], resumableChapters: [], hydratedChapter: null,
      hydrateEpoch: 0, liveRun: false, lastAutoSave: null,
      styleRewriting: { agent: 'narration' },
    }
    expect(authorLoopReducer(base, wsEventReceived({ type: 'author_loop_done' })).styleRewriting).toBeNull()
    expect(authorLoopReducer(base, wsEventReceived({ type: 'author_loop_error', error: 'x' })).styleRewriting).toBeNull()
    expect(authorLoopReducer(base, wsEventReceived({ type: 'author_loop_stopped' })).styleRewriting).toBeNull()
  })
})

describe('authorLoopSlice thunks', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))
  afterEach(() => vi.unstubAllGlobals())

  it('startAuthorLoop sets running immediately, marks liveRun on success', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({}) })
    const store = buildStore()
    const promise = store.dispatch(startAuthorLoop(4) as never)
    expect(selectAuthorLoop(store.getState() as never)).toMatchObject({ status: 'running', chapter: 4 })
    await promise
    expect(selectAuthorLoopLiveRun(store.getState() as never)).toBe(true)
  })

  it('startAuthorLoop failure sets status=error with the message, does not mark liveRun', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: false, status: 500, json: async () => ({ error: '爆了' }) })
    const store = buildStore()
    const result = await store.dispatch(startAuthorLoop(4) as never) as { payload: { ok: boolean; error?: string } }
    expect(result.payload).toEqual({ ok: false, error: '爆了' })
    expect(selectAuthorLoop(store.getState() as never).status).toBe('error')
    expect(selectAuthorLoopLiveRun(store.getState() as never)).toBe(false)
  })

  it('resumeAuthorLoop keeps existing messages, marks liveRun on success', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({}) })
    const store = buildStore({ messages: [{ id: 'x' }] as never, total: 3 })
    await store.dispatch(resumeAuthorLoop(2) as never)
    const state = selectAuthorLoop(store.getState() as never)
    expect(state.messages).toHaveLength(1)
    expect(state.total).toBe(3)
    expect(state.status).toBe('running')
    expect(selectAuthorLoopLiveRun(store.getState() as never)).toBe(true)
  })

  it('restartAuthorLoop drops the chapter from resumableChapters on success', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({}) })
    const store = buildStore({ resumableChapters: [2, 4] })
    await store.dispatch(restartAuthorLoop(4) as never)
    expect(selectResumableChapters(store.getState() as never)).toEqual([2])
  })

  it('stopAuthorLoop POSTs /api/author-loop/stop and never throws even on network failure', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('net down'))
    const store = buildStore()
    await expect(store.dispatch(stopAuthorLoop() as never)).resolves.toBeDefined()
    expect(fetch).toHaveBeenCalledWith('/api/author-loop/stop', { method: 'POST' })
  })

  it('saveAuthorLoop returns {ok:true,path} on success without touching authorLoop state', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({ ok: true, path: '/x.md' }) })
    const store = buildStore()
    const before = selectAuthorLoop(store.getState() as never)
    const result = await store.dispatch(saveAuthorLoop(3) as never) as { payload: { ok: boolean; path?: string } }
    expect(result.payload).toEqual({ ok: true, path: '/x.md' })
    expect(selectAuthorLoop(store.getState() as never)).toEqual(before)
  })

  it('fetchAuthorLoopStatus populates resumableChapters', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({ resumable: [1, 2], running_chapter: null }) })
    const store = buildStore()
    await store.dispatch(fetchAuthorLoopStatus(undefined) as never)
    expect(selectResumableChapters(store.getState() as never)).toEqual([1, 2])
    expect(fetch).toHaveBeenCalledWith('/api/author-loop/status')
  })

  it('fetchAuthorLoopStatus passes novel_id through when given', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({ resumable: [], running_chapter: null }) })
    const store = buildStore()
    await store.dispatch(fetchAuthorLoopStatus('novel-a') as never)
    expect(fetch).toHaveBeenCalledWith('/api/author-loop/status?novel_id=novel-a')
  })

  it('fetchAuthorLoopStatus with a running_chapter syncs the chapter selector and hydrates it', async () => {
    ;(fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ resumable: [], running_chapter: 7 }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ events: [{ type: 'author_loop_start', chapter: 7 }] }) })
    const store = configureStore({
      reducer: { authorLoop: authorLoopReducer, ui: uiReducer },
    })
    await store.dispatch(fetchAuthorLoopStatus('novel-a') as never)
    expect((store.getState() as { ui: { chapter: number } }).ui.chapter).toBe(7)
    expect(fetch).toHaveBeenCalledWith('/api/author-loop/journal?chapter=7&novel_id=novel-a')
  })

  it('hydrateAuthorLoop replays a paused chapter\'s journal and lands on idle', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        events: [
          { type: 'author_loop_segment', index: 0, text: '甲说话', total: 1 },
          { type: 'author_loop_stopped', chapter: 5 },
        ],
      }),
    })
    const store = buildStore({ resumableChapters: [5] })
    await store.dispatch(hydrateAuthorLoop({ chapter: 5 }) as never)
    const state = selectAuthorLoop(store.getState() as never)
    expect(state.chapter).toBe(5)
    expect(state.messages).toHaveLength(1)
    expect(state.status).toBe('idle')
  })

  it('hydrateAuthorLoop replays a still-running chapter\'s live tail and lands on running', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        events: [
          { type: 'author_loop_start', chapter: 5 },
          { type: 'author_loop_token', agent: 'director', delta: '他抬起头' },
        ],
      }),
    })
    const store = buildStore({ resumableChapters: [5] })
    await store.dispatch(hydrateAuthorLoop({ chapter: 5 }) as never)
    const state = selectAuthorLoop(store.getState() as never)
    expect(state.status).toBe('running')
    expect(state.live).toEqual([{ agent: 'director', role: undefined, text: '他抬起头' }])
  })

  it('hydrateAuthorLoop passes novel_id through to the journal fetch when given', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({ events: [] }) })
    const store = buildStore()
    await store.dispatch(hydrateAuthorLoop({ chapter: 5, novelId: 'novel-a' }) as never)
    expect(fetch).toHaveBeenCalledWith('/api/author-loop/journal?chapter=5&novel_id=novel-a')
  })

  it('hydrateAuthorLoop is a no-op when the chapter was already hydrated', async () => {
    const store = buildStore({ hydratedChapter: 5 })
    await store.dispatch(hydrateAuthorLoop({ chapter: 5 }) as never)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('syncAuthorLoopForChapter clears to a fresh idle view for a non-resumable chapter', async () => {
    const store = buildStore({ status: 'idle', resumableChapters: [], chapter: 1, messages: [{ id: 'x' }] as never })
    await store.dispatch(syncAuthorLoopForChapter(9) as never)
    const state = selectAuthorLoop(store.getState() as never)
    expect(state.chapter).toBe(9)
    expect(state.messages).toEqual([])
    expect(fetch).not.toHaveBeenCalled()
  })

  it('syncAuthorLoopForChapter hydrates a resumable chapter instead of clearing', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({ events: [] }) })
    const store = buildStore({ status: 'idle', resumableChapters: [9] })
    await store.dispatch(syncAuthorLoopForChapter(9) as never)
    expect(fetch).toHaveBeenCalledWith('/api/author-loop/journal?chapter=9')
  })

  it('syncAuthorLoopForChapter is a no-op while a run is in progress', async () => {
    const store = buildStore({ status: 'running' })
    await store.dispatch(syncAuthorLoopForChapter(9) as never)
    expect(fetch).not.toHaveBeenCalled()
  })
})

describe('authorLoopSlice: reset + internal flags', () => {
  it('resetAuthorLoop bumps hydrateEpoch and returns to a bare idle shape', () => {
    const prev = { status: 'error' as const, chapter: 3, total: 5, messages: [{ id: 'x' }] as never, resumableChapters: [1], hydratedChapter: 3, hydrateEpoch: 2, liveRun: true, lastAutoSave: null, error: 'x' }
    const state = authorLoopReducer(prev, resetAuthorLoop())
    expect(state.hydrateEpoch).toBe(3)
    expect(state.hydratedChapter).toBeNull()
    expect(state).toMatchObject({ status: 'idle', chapter: 0, total: 0, messages: [] })
    expect(state.error).toBeUndefined()
  })

  it('authorLoopLiveRunSet/authorLoopStalledSet toggle their own field only', () => {
    let state = authorLoopReducer(undefined, authorLoopLiveRunSet(true))
    expect(state.liveRun).toBe(true)
    state = authorLoopReducer(state, authorLoopStalledSet(true))
    expect(state.stalled).toBe(true)
    expect(state.liveRun).toBe(true)
  })

  it('authorLoopAutoSaveSettled records the outcome, authorLoopAutoSaveConsumed clears it', () => {
    let state = authorLoopReducer(undefined, authorLoopAutoSaveSettled({ ok: true, chapter: 3 }))
    expect(state.lastAutoSave).toEqual({ ok: true, chapter: 3 })
    state = authorLoopReducer(state, authorLoopAutoSaveConsumed())
    expect(state.lastAutoSave).toBeNull()
  })
})
