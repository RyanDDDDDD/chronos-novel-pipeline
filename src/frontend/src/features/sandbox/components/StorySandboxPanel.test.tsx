import React, { useEffect, useState } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Provider } from 'react-redux'
import { CHAT_HISTORY_SYNC_LABEL } from '@/shared/components/ChatHistorySyncOverlay'
import { renderWithProviders, buildTestStore } from '@/test/renderWithClient'
import Toaster from '@/shared/components/Toaster'
import { Toaster as Sonner } from '@/shared/components/ui/sonner'
import { useToast } from '@/shared/hooks/useToast'
import type { RootState } from '@/shared/store/store'
import { wsEventReceived, type OrchestratorEvent } from '@/shared/store/wsActions'
import StorySandboxPanel, { buildSubmissionText } from './StorySandboxPanel'
import {
  lockHistoricalRoundSuggestions,
  lockRoundSuggestions,
  reduceStorySandboxEvent,
  EMPTY_LIVE_ROUND,
  type ChatState,
} from '@/features/sandbox/utils/sandboxChatState'
import {
  readStoredSandboxMode,
  writeStoredSandboxMode,
  type SandboxMode,
} from '@/features/sandbox/utils/sandboxMode'

type StorySandboxPanelHarnessProps = Omit<
  React.ComponentProps<typeof StorySandboxPanel>,
  'mode' | 'onModeChange'
>

function StorySandboxPanelHarness(props: StorySandboxPanelHarnessProps) {
  const [mode, setMode] = useState<SandboxMode>(() => readStoredSandboxMode(props.novelId))
  useEffect(() => {
    setMode(readStoredSandboxMode(props.novelId))
  }, [props.novelId])
  const onModeChange = (next: 'chapter' | 'free') => {
    setMode(next)
    writeStoredSandboxMode(props.novelId, next)
  }
  return <StorySandboxPanel {...props} mode={mode} onModeChange={onModeChange} />
}

// ws/connected now come from the store (useWsClient()/selectConnected) instead of props --
// getWsInstance is mocked via a vi.hoisted holder so individual tests can plug in a fake
// WebSocket-like object (see the "during opening init" test below) while everything else just
// gets `null` (connected:true + no ws instance set, matching baseProps' old ws:null).
const wsHolder = vi.hoisted(() => ({ current: null as WebSocket | null }))
vi.mock('@/shared/store/wsMiddleware', () => ({ getWsInstance: () => wsHolder.current }))

// Same fake-ws shape as the "during opening init" test below (addEventListener/
// removeEventListener recording listeners by type) -- reused here so the new interrupt tests
// can push WS events without introducing a second fake-ws pattern into this file.
//
// A real WS message is now applied to state via wsMiddleware dispatching wsEventReceived at the
// store level (sandboxSlice's own reducer, independent of whatever's mounted) -- the panel's own
// onMsg listener (which this fake ws drives) only handles side effects that aren't pure state
// folding anymore (toasts, cache invalidation, composer-text restore on cancel). There's no real
// wsMiddleware wired into the test store (it opens a genuine WebSocket, which jsdom can't drive
// deterministically), so emit() dispatches wsEventReceived itself when given a store, mirroring
// both delivery paths a real WS message takes in production.
function makeFakeWs(store?: ReturnType<typeof buildTestStore>) {
  const listeners: Record<string, Array<(e: MessageEvent) => void>> = {}
  const ws = {
    addEventListener: (type: string, fn: (e: MessageEvent) => void) => {
      listeners[type] = listeners[type] ?? []
      listeners[type].push(fn)
    },
    removeEventListener: () => {},
  } as unknown as WebSocket
  const emit = (data: unknown) => {
    for (const fn of listeners.message ?? []) {
      fn({ data: JSON.stringify(data) } as MessageEvent)
    }
    store?.dispatch(wsEventReceived(data as OrchestratorEvent))
  }
  return { ws, emit }
}

async function clickBranchMenuItem(name: string | RegExp) {
  await userEvent.click(screen.getByRole('button', { name: '故事线操作' }))
  await userEvent.click(await screen.findByRole('menuitem', { name }))
}

// The confirm() toast is normally rendered by a single <Toaster> mounted at the App.tsx level,
// outside this component's own subtree -- mount a local host reading the same useToast()
// singleton alongside the panel so confirm/cancel buttons show up in this test's DOM too.
function ToasterHost() {
  const { toasts, dismiss } = useToast()
  return <><Toaster toasts={toasts} onDismiss={dismiss} /><Sonner /></>
}

function renderPanel(
  ui: React.ReactElement,
  opts: { activeNovelId?: string; preloadedState?: Partial<RootState> } = {},
) {
  return renderWithProviders(
    <>{ui}<ToasterHost /></>,
    {
      activeNovelId: opts.activeNovelId,
      preloadedState: { connection: { connected: true }, ...opts.preloadedState },
    },
  )
}

/** Builds the Redux store standalone, before rendering -- lets a test wire a store-aware fake ws
 * (see makeFakeWs) via wsHolder *before* mounting the panel, then render against that same store
 * with renderWithStore below. Needed by any test that both drives WS events and asserts on state
 * those events produce, since renderPanel's react-query/store instances aren't reachable. */
function buildPanelStore(preloadedState?: Partial<RootState>) {
  return buildTestStore({ connection: { connected: true }, ...preloadedState })
}

function renderWithStore(
  store: ReturnType<typeof buildTestStore>,
  ui: React.ReactElement,
  activeNovelId = 'default',
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  if (activeNovelId) client.setQueryData(['novels'], [{ id: activeNovelId, name: 'N', active: true }])
  return render(
    <Provider store={store}>
      <QueryClientProvider client={client}>
        <>{ui}<ToasterHost /></>
      </QueryClientProvider>
    </Provider>,
  )
}

type HistoryRound = {
  id?: string
  instruction?: string
  prose: string
  characterStates?: Record<string, unknown>
  suggestions?: string[]
  initialStates?: Record<string, unknown> | null
  sceneState?: Record<string, unknown>
  initialSceneState?: Record<string, unknown> | null
}

type SkeletonStageStub = { stage_num: number; description: string; location?: string }

function mockSandboxHistory(
  rounds: HistoryRound[] = [],
  skeletonStages: SkeletonStageStub[] = [],
  opts: {
    nextBranchAfterDelete?: { id: string; name: string }
    nextBranchAfterReset?: { id: string; name: string }
  } = {},
) {
  vi.spyOn(global, 'fetch').mockImplementation(async (url, init) => {
    const method = (init?.method ?? 'GET').toUpperCase()
    // Reset endpoint check must come before the generic branch-create POST check below --
    // POST .../branches/{id}/reset would otherwise also match that broader condition.
    if (String(url).includes('/api/story-sandbox/branches/') && String(url).includes('/reset') && method === 'POST') {
      const next = opts.nextBranchAfterReset ?? { id: 'b1', name: '故事线1' }
      return {
        ok: true,
        json: async () => ({
          ok: true,
          branch: { id: next.id, name: next.name, chapter: 1, created_at: '', updated_at: '' },
        }),
      } as Response
    }
    // Branch delete/create endpoints -- only the shapes the panel's own mutations need
    // (id/name of the branch to switch to / just created), not full CRUD fidelity.
    if (String(url).includes('/api/story-sandbox/branches/') && method === 'DELETE') {
      const next = opts.nextBranchAfterDelete ?? { id: 'b2', name: '故事线2' }
      return {
        ok: true,
        json: async () => ({
          ok: true,
          branch: { id: next.id, name: next.name, chapter: 1, created_at: '', updated_at: '' },
        }),
      } as Response
    }
    if (String(url).includes('/api/story-sandbox/branches') && method === 'POST') {
      return {
        ok: true,
        json: async () => ({
          ok: true,
          branch: { id: 'b-new', name: '新故事线', chapter: 1, created_at: '', updated_at: '' },
        }),
      } as Response
    }
    if (String(url).includes('/api/story-sandbox/history')) {
      return {
        ok: true,
        json: async () => ({
          rounds: rounds.map((r) => ({
            id: r.id,
            instruction: r.instruction ?? '继续',
            prose: r.prose,
            character_states: r.characterStates ?? {},
            suggestions: r.suggestions ?? [],
            initial_states: r.initialStates ?? null,
            scene_state: r.sceneState ?? {},
            initial_scene_state: r.initialSceneState ?? null,
          })),
        }),
      } as Response
    }
    if (String(url).includes('/api/setup/skeleton/')) {
      return {
        ok: true,
        json: async () => ({
          chapter: 0,
          exists: skeletonStages.length > 0,
          stages: skeletonStages.map((s) => ({ ...s, beats: [], expanded: false })),
        }),
      } as Response
    }
    return { ok: true, json: async () => ({}) } as Response
  })
}

describe('reduceStorySandboxEvent', () => {
  const empty: ChatState = {
    rounds: [], liveRound: null, status: '', rewritingProse: null, styleRewriting: false,
    selectionRewriting: false, pendingFields: {},
  }

  it('story_sandbox_style_rewrite start sets styleRewriting true and end clears it', () => {
    let s = reduceStorySandboxEvent(empty, { type: 'story_sandbox_style_rewrite', status: 'start' })
    expect(s.styleRewriting).toBe(true)
    s = reduceStorySandboxEvent(s, { type: 'story_sandbox_style_rewrite', status: 'end' })
    expect(s.styleRewriting).toBe(false)
  })

  it('story_sandbox_final marks characterStates pending until states arrive', () => {
    let s = reduceStorySandboxEvent(empty, { type: 'story_sandbox_final', content: '定稿正文' })
    expect(s.pendingFields).toEqual({ characterStates: true, sceneState: true })
    s = reduceStorySandboxEvent(s, {
      type: 'story_sandbox_states',
      states: { 甲: { psychology: '平静' } },
      scene_state: {},
    })
    // states arriving both clears characterStates and marks suggestions pending next
    expect(s.pendingFields).toEqual({ suggestions: true })
    s = reduceStorySandboxEvent(s, {
      type: 'story_sandbox_suggestions', options: ['某建议'],
    })
    expect(s.pendingFields).toEqual({})
  })

  it('story_sandbox_initial_states clears the initialStates pending flag', () => {
    const seeded: ChatState = { ...empty, pendingFields: { initialStates: true, initialSceneState: true } }
    const s = reduceStorySandboxEvent(seeded, {
      type: 'story_sandbox_initial_states',
      states: { 甲: { psychology: '外冷内热' } },
      scene_state: { description: '书房' },
    })
    expect(s.pendingFields).toEqual({})
  })

  it('accumulates streamed tokens into liveRound.prose', () => {
    let s = reduceStorySandboxEvent(empty, { type: 'story_sandbox_token', delta: '他抬起头，' })
    s = reduceStorySandboxEvent(s, { type: 'story_sandbox_token', delta: '看向窗外。' })
    expect(s.liveRound?.prose).toBe('他抬起头，看向窗外。')
  })

  it('story_sandbox_states sets liveRound.characterStates', () => {
    const s = reduceStorySandboxEvent(empty, {
      type: 'story_sandbox_states',
      states: { 甲: { personality: '平静' } },
      scene_state: {},
    })
    expect(s.liveRound?.characterStates).toEqual({ 甲: { personality: '平静' } })
  })

  it('story_sandbox_suggestions sets liveRound.suggestions', () => {
    const s = reduceStorySandboxEvent(empty, {
      type: 'story_sandbox_suggestions', options: ['甲追出去解释'],
    })
    expect(s.liveRound?.suggestions).toEqual(['甲追出去解释'])
  })

  it('story_sandbox_suggestions_regenerated replaces the last round\'s suggestions and clears pending', () => {
    const seeded: ChatState = {
      ...empty,
      pendingFields: { suggestions: true },
      rounds: [
        { instruction: '继续', prose: '他抬起头。', characterStates: {}, suggestions: ['旧建议'], sceneState: {} },
      ],
    }
    const s = reduceStorySandboxEvent(seeded, {
      type: 'story_sandbox_suggestions_regenerated', options: ['新建议A'],
    })
    expect(s.rounds[0].suggestions).toEqual(['新建议A'])
    expect(s.pendingFields).toEqual({})
  })

  it('story_sandbox_suggestions_regenerated with no rounds only clears pending', () => {
    const seeded: ChatState = { ...empty, pendingFields: { suggestions: true } }
    const s = reduceStorySandboxEvent(seeded, {
      type: 'story_sandbox_suggestions_regenerated', options: ['新建议A'],
    })
    expect(s.rounds).toEqual([])
    expect(s.pendingFields).toEqual({})
  })

  it('story_sandbox_suggestions_regenerate_error clears pending without touching rounds', () => {
    const seeded: ChatState = {
      ...empty,
      pendingFields: { suggestions: true },
      rounds: [
        { instruction: '继续', prose: '他抬起头。', characterStates: {}, suggestions: ['旧建议'], sceneState: {} },
      ],
    }
    const s = reduceStorySandboxEvent(seeded, {
      type: 'story_sandbox_suggestions_regenerate_error', error: '有任务运行中',
    })
    expect(s.rounds[0].suggestions).toEqual(['旧建议'])
    expect(s.pendingFields).toEqual({})
  })

  it('story_sandbox_done pushes liveRound into rounds and clears it', () => {
    let s = reduceStorySandboxEvent(
      { ...empty, styleRewriting: true },
      { type: 'story_sandbox_token', delta: '正文' },
    )
    s = reduceStorySandboxEvent(s, { type: 'story_sandbox_done' })
    expect(s.liveRound).toBeNull()
    expect(s.rounds).toHaveLength(1)
    expect(s.rounds[0].prose).toBe('正文')
    expect(s.styleRewriting).toBe(false)
  })

  it('story_sandbox_done with no liveRound leaves rounds untouched', () => {
    const s = reduceStorySandboxEvent(
      { ...empty, styleRewriting: true },
      { type: 'story_sandbox_done' },
    )
    expect(s.rounds).toEqual([])
    expect(s.styleRewriting).toBe(false)
  })

  it('story_sandbox_done with a prose-less liveRound does not append a duplicate round', () => {
    const s = reduceStorySandboxEvent(
      {
        ...empty,
        rounds: [{
          instruction: 'a', prose: 'p', characterStates: {}, suggestions: ['甲'], suggestionsLocked: true,
        }],
        liveRound: { ...EMPTY_LIVE_ROUND, instruction: 'next', prose: '', suggestions: [] },
      },
      { type: 'story_sandbox_done' },
    )
    expect(s.rounds).toHaveLength(1)
    expect(s.liveRound?.instruction).toBe('next')
  })

  it('story_sandbox_error appends an error round and clears liveRound and rewritingProse', () => {
    const s = reduceStorySandboxEvent(
      { ...empty, rewritingProse: '甲缓缓', styleRewriting: true },
      { type: 'story_sandbox_error', error: '连接失败' },
    )
    expect(s.rounds[0].prose).toContain('连接失败')
    expect(s.rounds[0].errorCode).toBeUndefined()
    expect(s.liveRound).toBeNull()
    expect(s.rewritingProse).toBeNull()
    expect(s.styleRewriting).toBe(false)
  })

  it('story_sandbox_error with code marks the error round retryable', () => {
    const s = reduceStorySandboxEvent(empty, {
      type: 'story_sandbox_error', error: '推演失败', code: 'SCENE_DERIVE_FAILED',
    })
    expect(s.rounds[0].errorCode).toBe('SCENE_DERIVE_FAILED')
  })

  it('story_sandbox_turn_cancelled clears liveRound and styleRewriting', () => {
    const s = reduceStorySandboxEvent(
      { ...empty, liveRound: { instruction: '继续', prose: '生成中', characterStates: {}, suggestions: [], initialStates: null, sceneState: {}, initialSceneState: null, eventLogEntries: [], rollingSummaryAfter: '', recallContext: '', profileMutation: null }, styleRewriting: true },
      { type: 'story_sandbox_turn_cancelled', chapter: 1, rollback_failed: false },
    )
    expect(s.liveRound).toBeNull()
    expect(s.styleRewriting).toBe(false)
  })

  it('story_sandbox_turn_cancelled also clears an in-flight rewritingProse, so the rewrite box unsticks', () => {
    const s = reduceStorySandboxEvent(
      { ...empty, rewritingProse: '甲缓缓' },
      { type: 'story_sandbox_turn_cancelled', chapter: 1, rollback_failed: false },
    )
    expect(s.rewritingProse).toBeNull()
  })

  it('story_sandbox_initial_states sets liveRound.initialStates', () => {
    const s = reduceStorySandboxEvent(empty, {
      type: 'story_sandbox_initial_states',
      states: { 甲: { personality: '外冷内热' } },
      scene_state: {},
    })
    expect(s.liveRound?.initialStates).toEqual({ 甲: { personality: '外冷内热' } })
  })

  it('story_sandbox_done carries initialStates through into the pushed round', () => {
    let s = reduceStorySandboxEvent(empty, {
      type: 'story_sandbox_initial_states',
      states: { 甲: { personality: '外冷内热' } },
      scene_state: {},
    })
    s = reduceStorySandboxEvent(s, { type: 'story_sandbox_token', delta: '正文' })
    s = reduceStorySandboxEvent(s, { type: 'story_sandbox_done' })
    expect(s.rounds[0].initialStates).toEqual({ 甲: { personality: '外冷内热' } })
  })

  it('story_sandbox_rewrite_token accumulates into rewritingProse', () => {
    let s = reduceStorySandboxEvent(empty, { type: 'story_sandbox_rewrite_token', delta: '甲缓缓' })
    s = reduceStorySandboxEvent(s, { type: 'story_sandbox_rewrite_token', delta: '抬起头。' })
    expect(s.rewritingProse).toBe('甲缓缓抬起头。')
  })

  it('story_sandbox_rewrite_done replaces the last round and clears rewritingProse', () => {
    const withRound: ChatState = {
      rounds: [{
        instruction: '甲乙对峙', prose: '旧正文', characterStates: {}, suggestions: ['旧建议'], sceneState: {},
      }],
      liveRound: null, status: '', rewritingProse: '甲缓缓', styleRewriting: true, pendingFields: {},
    }
    const s = reduceStorySandboxEvent(withRound, {
      type: 'story_sandbox_rewrite_done', content: '新正文',
      suggestions: ['新建议'], states: { 甲: { personality: '冷淡' } }, scene_state: {},
      recall_context: '', recalled_settings: [], entries: [], rolling_summary: '', mutation: null,
    })
    expect(s.rewritingProse).toBeNull()
    expect(s.styleRewriting).toBe(false)
    expect(s.liveRound).toBeNull()
    expect(s.rounds).toHaveLength(1)
    expect(s.rounds[0]).toEqual({
      instruction: '甲乙对峙', prose: '新正文',
      characterStates: { 甲: { personality: '冷淡' } }, suggestions: ['新建议'], sceneState: {},
      recallContext: '', recalledSettings: [], eventLogEntries: [], rollingSummaryAfter: '',
      profileMutation: null, relationshipMutation: null,
    })
  })

  it('story_sandbox_rewrite_done refreshes event log entry and profile mutation, discarding stale ones', () => {
    const withRound: ChatState = {
      rounds: [{
        instruction: '甲乙对峙', prose: '旧正文', characterStates: {}, suggestions: [], sceneState: {},
        eventLogEntries: [{ summary: '旧事件', time: '上午' }], rollingSummaryAfter: '旧摘要',
        profileMutation: { 甲: { sliders: { warmth: 0 } } },
      }],
      liveRound: null, status: '', rewritingProse: '甲缓缓',
    }
    const s = reduceStorySandboxEvent(withRound, {
      type: 'story_sandbox_rewrite_done', content: '新正文',
      suggestions: [], states: {}, scene_state: {}, recall_context: '', recalled_settings: [],
      entries: [{ summary: '新事件', time: '傍晚' }], rolling_summary: '新摘要',
      mutation: { 甲: { sliders: { warmth: 1 } } },
    })
    expect(s.rounds[0].eventLogEntries).toEqual([{ summary: '新事件', time: '傍晚' }])
    expect(s.rounds[0].rollingSummaryAfter).toBe('新摘要')
    expect(s.rounds[0].profileMutation).toEqual({ 甲: { sliders: { warmth: 1 } } })
  })

  it('story_sandbox_rewrite_done with a null entry/mutation clears the prior stale ones', () => {
    const withRound: ChatState = {
      rounds: [{
        instruction: '甲乙对峙', prose: '旧正文', characterStates: {}, suggestions: [], sceneState: {},
        eventLogEntries: [{ summary: '旧事件', time: '上午' }],
        profileMutation: { 甲: { sliders: { warmth: 0 } } },
      }],
      liveRound: null, status: '', rewritingProse: '甲缓缓',
    }
    const s = reduceStorySandboxEvent(withRound, {
      type: 'story_sandbox_rewrite_done', content: '新正文',
      suggestions: [], states: {}, scene_state: {}, recall_context: '', recalled_settings: [],
      entries: [], rolling_summary: '', mutation: null,
    })
    expect(s.rounds[0].eventLogEntries).toEqual([])
    expect(s.rounds[0].profileMutation).toBeNull()
  })

  it('story_sandbox_rewrite_done without states/suggestions keeps the prior round fields', () => {
    const withRound: ChatState = {
      rounds: [{
        instruction: '甲乙对峙', prose: '旧正文',
        characterStates: { 甲: { psychology: '平静' } }, suggestions: ['旧建议'], sceneState: {}
      }],
      liveRound: null, status: '', rewritingProse: '甲缓缓',
    }
    const s = reduceStorySandboxEvent(withRound, {
      type: 'story_sandbox_rewrite_done', content: '新正文',
    } as Parameters<typeof reduceStorySandboxEvent>[1])
    expect(s.rounds[0]).toEqual({
      instruction: '甲乙对峙', prose: '新正文',
      characterStates: { 甲: { psychology: '平静' } }, suggestions: ['旧建议'], sceneState: {},
      recallContext: '', recalledSettings: [], eventLogEntries: [], rollingSummaryAfter: '',
      profileMutation: null, relationshipMutation: null,
    })
    expect(s.liveRound).toBeNull()
  })

  it('story_sandbox_states during a rewrite does not spawn a phantom liveRound', () => {
    const rewriting: ChatState = {
      rounds: [{
        instruction: '甲乙对峙', prose: '旧正文', characterStates: {}, suggestions: [], sceneState: {},
      }],
      liveRound: null, status: '', rewritingProse: '甲缓缓', pendingFields: { characterStates: true },
    }
    const s = reduceStorySandboxEvent(rewriting, {
      type: 'story_sandbox_states',
      states: { 甲: { personality: '冷淡' } },
      scene_state: {},
    })
    expect(s.liveRound).toBeNull()
    expect(s.pendingFields).toEqual({ suggestions: true })
  })

  it('story_sandbox_suggestions during a rewrite does not spawn a phantom liveRound', () => {
    const rewriting: ChatState = {
      rounds: [{
        instruction: '甲乙对峙', prose: '旧正文', characterStates: {}, suggestions: [], sceneState: {},
      }],
      liveRound: null, status: '', rewritingProse: '甲缓缓', pendingFields: { suggestions: true },
    }
    const s = reduceStorySandboxEvent(rewriting, {
      type: 'story_sandbox_suggestions', options: ['新建议'],
    })
    expect(s.liveRound).toBeNull()
    expect(s.pendingFields).toEqual({})
  })

  it('story_sandbox_event_log records entry and rolling summary on liveRound', () => {
    const liveRound = {
      instruction: '继续', prose: '正文', characterStates: {}, suggestions: [],
      initialStates: null, sceneState: {}, initialSceneState: null, eventLogEntries: [],
      rollingSummaryAfter: '', recallContext: '',
    }
    const s = reduceStorySandboxEvent(
      {
        rounds: [], liveRound, status: '', rewritingProse: null, pendingFields: {},
      },
      {
        type: 'story_sandbox_event_log',
        entries: [{ summary: '甲做了事', time: '决战之后' }],
        rolling_summary: '目前为止的摘要',
      },
    )
    expect(s.liveRound?.eventLogEntries).toEqual([{ summary: '甲做了事', time: '决战之后' }])
    expect(s.liveRound?.rollingSummaryAfter).toBe('目前为止的摘要')
  })

  it('story_sandbox_event_log updates rolling summary even when this round has no event entry', () => {
    const liveRound = {
      instruction: '继续', prose: '正文', characterStates: {}, suggestions: [],
      initialStates: null, sceneState: {}, initialSceneState: null, eventLogEntries: [],
      rollingSummaryAfter: '',
    }
    const s = reduceStorySandboxEvent(
      {
        rounds: [], liveRound, status: '', rewritingProse: null, pendingFields: {},
      },
      { type: 'story_sandbox_event_log', entries: [], rolling_summary: '没有事件也照样更新的摘要' },
    )
    expect(s.liveRound?.eventLogEntries).toEqual([])
    expect(s.liveRound?.rollingSummaryAfter).toBe('没有事件也照样更新的摘要')
  })

  it('story_sandbox_event_log during rewrite does not spawn a phantom liveRound', () => {
    const s = reduceStorySandboxEvent(
      {
        rounds: [], liveRound: null, status: '', rewritingProse: '甲缓缓', pendingFields: {},
      },
      { type: 'story_sandbox_event_log', entries: [{ summary: '甲做了事', time: '' }], rolling_summary: '摘要' },
    )
    expect(s.liveRound).toBeNull()
  })

  it('story_sandbox_profile_mutation records mutation on liveRound', () => {
    const liveRound = {
      instruction: '继续', prose: '正文', characterStates: {}, suggestions: [],
      initialStates: null, sceneState: {}, initialSceneState: null, eventLogEntries: [],
      rollingSummaryAfter: '', recallContext: '', profileMutation: null,
    }
    const s = reduceStorySandboxEvent(
      { rounds: [], liveRound, status: '', rewritingProse: null, pendingFields: {} },
      { type: 'story_sandbox_profile_mutation', mutation: { 甲: { race: '精灵' } } },
    )
    expect(s.liveRound?.profileMutation).toEqual({ 甲: { race: '精灵' } })
  })

  it('story_sandbox_profile_mutation during rewrite does not spawn a phantom liveRound', () => {
    const s = reduceStorySandboxEvent(
      { rounds: [], liveRound: null, status: '', rewritingProse: '甲缓缓', pendingFields: {} },
      { type: 'story_sandbox_profile_mutation', mutation: { 甲: { race: '精灵' } } },
    )
    expect(s.liveRound).toBeNull()
  })

  it('story_sandbox_recall_context records recall context on liveRound', () => {
    const liveRound = {
      instruction: '继续', prose: '正文', characterStates: {}, suggestions: [],
      initialStates: null, sceneState: {}, initialSceneState: null, eventLogEntries: [],
      rollingSummaryAfter: '', recallContext: '', recalledSettings: [],
    }
    const s = reduceStorySandboxEvent(
      { rounds: [], liveRound, status: '', rewritingProse: null, pendingFields: {} },
      {
        type: 'story_sandbox_recall_context',
        recall_context: '## 相关历史/设定回收\n- 甲做了事', recalled_settings: [],
      },
    )
    expect(s.liveRound?.recallContext).toBe('## 相关历史/设定回收\n- 甲做了事')
  })

  it('story_sandbox_recall_context during rewrite does not spawn a phantom liveRound', () => {
    const s = reduceStorySandboxEvent(
      { rounds: [], liveRound: null, status: '', rewritingProse: '甲缓缓', pendingFields: {} },
      { type: 'story_sandbox_recall_context', recall_context: '召回内容', recalled_settings: [] },
    )
    expect(s.liveRound).toBeNull()
  })

  it('story_sandbox_rewrite_done carries recall_context onto the replaced round', () => {
    const withRound: ChatState = {
      rounds: [{
        instruction: '继续', prose: '旧正文', characterStates: {}, suggestions: [],
        sceneState: {}, recallContext: '旧的召回',
      }],
      liveRound: null, status: '', rewritingProse: '新', pendingFields: {},
    }
    const s = reduceStorySandboxEvent(withRound, {
      type: 'story_sandbox_rewrite_done', content: '新正文',
      suggestions: [], states: {}, scene_state: {}, recall_context: '新的召回',
      recalled_settings: [], entries: [], rolling_summary: '', mutation: null,
    })
    expect(s.rounds[0].recallContext).toBe('新的召回')
  })

  it('story_sandbox_rewrite_done with no rounds only clears rewritingProse', () => {
    const s = reduceStorySandboxEvent(
      { rounds: [], liveRound: null, status: '', rewritingProse: '甲缓缓', styleRewriting: true, pendingFields: {} },
      {
        type: 'story_sandbox_rewrite_done', content: '新正文', suggestions: [], states: {},
        scene_state: {}, recall_context: '', recalled_settings: [], entries: [], rolling_summary: '',
        mutation: null,
      },
    )
    expect(s.rewritingProse).toBeNull()
    expect(s.styleRewriting).toBe(false)
    expect(s.rounds).toEqual([])
  })

  it('story_sandbox_recall_context 事件把 recalled_settings 写进 liveRound', () => {
    const s = reduceStorySandboxEvent(
      { rounds: [], liveRound: null, status: '', rewritingProse: null, pendingFields: {} },
      {
        type: 'story_sandbox_recall_context',
        recall_context: '## 相关历史/设定回收\n- 【元气】气血流动力量',
        recalled_settings: [{ category: 'power_system', name: '元气', desc: '气血流动力量' }],
      },
    )
    expect(s.liveRound?.recalledSettings).toEqual([
      { category: 'power_system', name: '元气', desc: '气血流动力量' },
    ])
  })

  it('story_sandbox_rewrite_done 事件把 recalled_settings 写进最后一轮', () => {
    const seeded: ChatState = {
      rounds: [{
        instruction: '继续', prose: '旧正文', characterStates: {}, suggestions: [], sceneState: {},
      }],
      liveRound: null, status: '', rewritingProse: '新', pendingFields: {},
    }
    const s = reduceStorySandboxEvent(seeded, {
      type: 'story_sandbox_rewrite_done',
      content: '新正文', suggestions: [], states: {}, scene_state: {},
      recall_context: '', recalled_settings: [{ category: 'races', name: '人族', desc: '凡躯' }],
      entries: [], rolling_summary: '', mutation: null,
    })
    expect(s.rounds[0].recalledSettings).toEqual([{ category: 'races', name: '人族', desc: '凡躯' }])
  })

  it('story_sandbox_selection_rewrite_start sets selectionRewriting', () => {
    const s = reduceStorySandboxEvent(empty, { type: 'story_sandbox_selection_rewrite_start' })
    expect(s.selectionRewriting).toBe(true)
  })

  it('story_sandbox_selection_rewrite_done replaces the last round prose and clears selectionRewriting', () => {
    const prev: ChatState = {
      rounds: [{ instruction: '继续', prose: '旧正文', characterStates: {}, suggestions: [], sceneState: {} }],
      liveRound: null, status: '', rewritingProse: null, styleRewriting: false,
      selectionRewriting: true,
      selectionRewritingAnchor: { originalText: '旧', anchorOffset: 0 },
      pendingFields: {},
    }
    const s = reduceStorySandboxEvent(prev, {
      type: 'story_sandbox_selection_rewrite_done', content: '新正文',
    })
    expect(s.rounds[0].prose).toBe('新正文')
    expect(s.selectionRewriting).toBe(false)
    expect(s.selectionRewritingAnchor).toBeNull()
  })

  it('story_sandbox_selection_rewrite_done with no rounds only clears selectionRewriting', () => {
    const prev: ChatState = {
      rounds: [], liveRound: null, status: '', rewritingProse: null, styleRewriting: false,
      selectionRewriting: true, pendingFields: {},
    }
    const s = reduceStorySandboxEvent(prev, {
      type: 'story_sandbox_selection_rewrite_done', content: '新正文',
    })
    expect(s.rounds).toEqual([])
    expect(s.selectionRewriting).toBe(false)
  })

  it('story_sandbox_selection_rewrite_error clears selectionRewriting without touching rounds', () => {
    const prev: ChatState = {
      rounds: [{ instruction: '继续', prose: '旧正文', characterStates: {}, suggestions: [], sceneState: {} }],
      liveRound: null, status: '', rewritingProse: null, styleRewriting: false,
      selectionRewriting: true, pendingFields: {},
    }
    const s = reduceStorySandboxEvent(prev, {
      type: 'story_sandbox_selection_rewrite_error', error: '选区未能定位',
    })
    expect(s.rounds[0].prose).toBe('旧正文')
    expect(s.selectionRewriting).toBe(false)
  })

  it('story_sandbox_selection_rewrite_start stamps selectionRewritingRoundId from round_id', () => {
    const s = reduceStorySandboxEvent(empty, {
      type: 'story_sandbox_selection_rewrite_start', round_id: 'round-2',
    })
    expect(s.selectionRewriting).toBe(true)
    expect(s.selectionRewritingRoundId).toBe('round-2')
  })

  it('story_sandbox_selection_rewrite_done targets the round matching round_id, not always the last round -- a request queued while an earlier round was still generating can fire after a newer round has since been appended', () => {
    const prev: ChatState = {
      rounds: [
        { id: 'round-1', instruction: '继续', prose: '旧正文1', characterStates: {}, suggestions: [], sceneState: {} },
        { id: 'round-2', instruction: '继续', prose: '旧正文2', characterStates: {}, suggestions: [], sceneState: {} },
      ],
      liveRound: null, status: '', rewritingProse: null, styleRewriting: false,
      selectionRewriting: true, selectionRewritingRoundId: 'round-1', pendingFields: {},
    }
    const s = reduceStorySandboxEvent(prev, {
      type: 'story_sandbox_selection_rewrite_done', content: '新正文1', round_id: 'round-1',
    })
    expect(s.rounds[0].prose).toBe('新正文1')
    expect(s.rounds[1].prose).toBe('旧正文2')
    expect(s.selectionRewriting).toBe(false)
    expect(s.selectionRewritingRoundId).toBeNull()
  })

  it('story_sandbox_selection_rewrite_done falls back to the last round when round_id is absent', () => {
    const prev: ChatState = {
      rounds: [{ id: 'round-1', instruction: '继续', prose: '旧正文', characterStates: {}, suggestions: [], sceneState: {} }],
      liveRound: null, status: '', rewritingProse: null, styleRewriting: false,
      selectionRewriting: true, pendingFields: {},
    }
    const s = reduceStorySandboxEvent(prev, {
      type: 'story_sandbox_selection_rewrite_done', content: '新正文',
    })
    expect(s.rounds[0].prose).toBe('新正文')
  })

  it('story_sandbox_suggestions stamps round_id onto liveRound.id (the "suggest" node is what appends the round on the backend)', () => {
    const seeded: ChatState = {
      ...empty,
      liveRound: {
        instruction: '继续', prose: '生成中', characterStates: {}, suggestions: [],
        initialStates: null, sceneState: {}, initialSceneState: null, eventLogEntries: [],
        rollingSummaryAfter: '', recallContext: '', recalledSettings: [], profileMutation: null,
      },
    }
    const s = reduceStorySandboxEvent(seeded, {
      type: 'story_sandbox_suggestions', options: ['甲'], round_id: 'round-new',
    })
    expect(s.liveRound?.id).toBe('round-new')
  })
})

// applySandboxHistoryRestore's old test coverage (scope-clear, in-flight-round merge protection,
// live_round replay per mode, opening-round pendingFields priming) now lives in
// sandboxSlice.test.ts's "live-chat hydration" describe block, since that reconciliation moved
// into hydrateSandboxChat -- it's the store, not this component, that owns rehydrating a scope.

describe('lockRoundSuggestions', () => {
  it('locks every open round, recording only the options actually submitted', () => {
    const rounds = [
      { instruction: 'a', prose: 'p1', characterStates: {}, suggestions: ['甲', '乙'] },
      { instruction: 'b', prose: 'p2', characterStates: {}, suggestions: ['丙'] },
    ]
    const locked = lockRoundSuggestions(rounds, ['甲', '丙'])
    expect(locked[0].submittedDirections).toEqual(['甲'])
    expect(locked[0].suggestionsLocked).toBe(true)
    expect(locked[1].submittedDirections).toEqual(['丙'])
    expect(locked[1].suggestionsLocked).toBe(true)
  })

  it('locks an open round even when nothing was picked from it (free-text send)', () => {
    const rounds = [
      { instruction: 'a', prose: 'p1', characterStates: {}, suggestions: ['甲', '乙'] },
    ]
    const locked = lockRoundSuggestions(rounds, [])
    expect(locked[0].suggestionsLocked).toBe(true)
    expect(locked[0].submittedDirections).toEqual([])
  })

  it('leaves already-locked rounds untouched', () => {
    const rounds = [
      {
        instruction: 'a', prose: 'p1', characterStates: {}, suggestions: ['甲'],
        suggestionsLocked: true, submittedDirections: ['甲'],
      },
    ]
    const locked = lockRoundSuggestions(rounds, [])
    expect(locked[0]).toBe(rounds[0])
  })
})

describe('lockHistoricalRoundSuggestions', () => {
  it('locks every round except the last when it has suggestions', () => {
    const rounds = [
      { instruction: 'a', prose: 'p1', characterStates: {}, suggestions: ['甲'] },
      { instruction: 'b', prose: 'p2', characterStates: {}, suggestions: ['乙'] },
    ]
    const locked = lockHistoricalRoundSuggestions(rounds)
    expect(locked[0].suggestionsLocked).toBe(true)
    expect(locked[1].suggestionsLocked).toBeUndefined()
  })
})

// Native jsdom localStorage isn't reliable under this project's Vitest/Node setup (its .clear
// is undefined) -- same workaround theme.test.ts already uses. sessionStorage works natively,
// no stub needed for it.
function mockLocalStorage() {
  const store = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => { store.set(k, v) },
    removeItem: (k: string) => { store.delete(k) },
    clear: () => { store.clear() },
  })
}

function mockMatchMedia() {
  const matchMediaMock = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
  vi.stubGlobal('matchMedia', matchMediaMock)
  if (typeof window !== 'undefined') {
    Object.defineProperty(window, 'matchMedia', { writable: true, configurable: true, value: matchMediaMock })
  }
}

describe('buildSubmissionText', () => {
  it('方向+记忆+正文都非空时按 方向→记忆→正文 顺序拼接', () => {
    const text = buildSubmissionText('自由输入', ['方向A'], ['[回忆] 第1章：旧事件'])
    expect(text).toBe('- 方向A\n\n[回忆] 第1章：旧事件\n\n自由输入')
  })

  it('无记忆时行为与两参数版本一致', () => {
    expect(buildSubmissionText('自由输入', ['方向A'])).toBe('- 方向A\n\n自由输入')
  })

  it('只有记忆没有方向和正文时只输出记忆', () => {
    expect(buildSubmissionText('', [], ['[回忆] 第1章：旧事件'])).toBe('[回忆] 第1章：旧事件')
  })
})

describe('StorySandboxPanel', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn()
    mockSandboxHistory()
    sessionStorage.clear()
    mockLocalStorage()
    mockMatchMedia()
    for (const id of ['novel-1', 'novelA', 'novelB']) {
      localStorage.setItem(`story-sandbox-mode:${id}`, 'chapter')
    }
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    wsHolder.current = null
    cleanup()
  })

  const baseProps = {
    novelId: 'novel-1', selectedChapter: 1, chapters: [1], onSelectChapter: vi.fn(),
    branchId: 'b1', onBranchChange: vi.fn(),
    sendMessage: vi.fn().mockResolvedValue({ ok: true }),
    stopTurn: vi.fn().mockResolvedValue({ ok: true }),
    regenerateSuggestions: vi.fn().mockResolvedValue({ ok: true }),
    startRewrite: vi.fn().mockResolvedValue({ ok: true }),
    retryDerive: vi.fn().mockResolvedValue({ ok: true }),
  }

  it('history 请求未完成时禁用输入框并显示同步提示', async () => {
    let resolveHistory: (v: Response) => void = () => {}
    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      if (String(url).includes('/api/story-sandbox/history')) {
        return new Promise<Response>((resolve) => { resolveHistory = resolve })
      }
      return { ok: true, json: async () => ({}) } as Response
    })

    const { getByRole, getByText, queryByText } = renderPanel(
      <StorySandboxPanelHarness {...baseProps} />, { activeNovelId: 'novel-1' },
    )

    await waitFor(() => expect(getByText(CHAT_HISTORY_SYNC_LABEL)).toBeTruthy())
    expect((getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(true)

    resolveHistory({
      ok: true,
      json: async () => ({ rounds: [] }),
    } as Response)

    await waitFor(() => expect(queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    expect((getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false)
  })

  it('refetches history when novelId becomes available after refresh', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch')
    mockSandboxHistory([{ instruction: '继续', prose: '他抬起头。' }])
    const { rerender } = renderPanel(
      <StorySandboxPanelHarness {...baseProps} novelId="" />, { activeNovelId: 'novel-1' },
    )
    expect(fetchSpy.mock.calls.some(([url]) => String(url).includes('/api/story-sandbox/history'))).toBe(false)
    rerender(<StorySandboxPanelHarness {...baseProps} novelId="novel-1" />)
    expect(await screen.findByText('他抬起头。')).toBeTruthy()
    expect(screen.getByText('继续')).toBeTruthy()
  })

  it('renders history rounds via TurnSegments', async () => {
    mockSandboxHistory([{ instruction: '继续', prose: '他抬起头。' }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    expect(await screen.findByText('他抬起头。')).toBeTruthy()
  })

  it('点击剧情走向选项后自动 focus 底部输入框', async () => {
    mockSandboxHistory([{
      instruction: '继续', prose: '他抬起头。', suggestions: ['甲追出去解释'],
    }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('他抬起头。')
    const pill = await screen.findByRole('button', { name: '甲追出去解释' })
    fireEvent.click(pill)
    expect(document.activeElement).toBe(screen.getByPlaceholderText(/给导演指令/))
  })

  it('renders opening initial state in a separate card from the first turn', async () => {
    mockSandboxHistory([{
      instruction: '甲乙对峙', prose: '他抬起头。',
      initialStates: { 甲: { psychology: '外冷内热' } },
    }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText(/🧬 角色进入态（初始）/)
    expect(screen.getByText('甲乙对峙')).toBeTruthy()
    expect(screen.getByText('他抬起头。')).toBeTruthy()
    // +1 for the panel's own outer bordered card (see StorySandboxPanel's root wrapper).
    const cards = document.querySelectorAll('.rounded-lg.border')
    expect(cards.length).toBe(3)
  })

  it('during opening init, shows only the init card until initial states arrive', async () => {
    mockSandboxHistory([])
    const store = buildPanelStore()
    const { ws, emit } = makeFakeWs(store)
    wsHolder.current = ws
    const sendMessage = vi.fn().mockResolvedValue({ ok: true })
    renderWithStore(store, <StorySandboxPanelHarness {...baseProps} sendMessage={sendMessage} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    const box = screen.getByPlaceholderText('给导演指令（Enter 发送，Shift+Enter 换行，@ 提及角色）…')
    fireEvent.change(box, {
      target: { value: '甲乙对峙' },
    })
    fireEvent.keyDown(box, { key: 'Enter' })
    expect(screen.getByText('正在推导角色进入态…')).toBeTruthy()
    expect(screen.queryByText('甲乙对峙')).toBeNull()
    emit({
      type: 'story_sandbox_initial_states',
      states: { 甲: { psychology: '外冷内热' } },
      scene_state: {},
    })
    await screen.findByText(/🧬 角色进入态（初始）/)
    expect(screen.getByText('甲乙对峙')).toBeTruthy()
    // +1 for the panel's own outer bordered card (see StorySandboxPanel's root wrapper).
    const cards = document.querySelectorAll('.rounded-lg.border')
    expect(cards.length).toBe(3)
  })

  it('restores submitted pill highlights after refresh when history omits submitted_directions', async () => {
    mockSandboxHistory([
      { instruction: '继续', prose: '他抬起头。', suggestions: ['甲追出去解释'] },
      { instruction: '- 甲追出去解释', prose: '他追了出去。', suggestions: ['乙沉默'] },
    ])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('他追了出去。')
    const summaries = screen.getAllByText(/🧭 剧情走向选择/)
    fireEvent.click(summaries[0])
    const pill = screen.getByRole('button', { name: '甲追出去解释' })
    expect(pill.getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByText(/已提交/)).toBeTruthy()
  })

  it('clicking a direction pill toggles selection without touching the input or resubmitting', async () => {
    const sendMessage = vi.fn().mockResolvedValue({ ok: true })
    mockSandboxHistory([{
      instruction: '继续', prose: '他抬起头。',
      suggestions: ['甲追出去解释'],
    }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} sendMessage={sendMessage} />)
    await screen.findByText('他抬起头。')
    fireEvent.click(screen.getByRole('button', { name: '甲追出去解释' }))
    const textarea = screen.getByPlaceholderText(
      '给导演指令（Enter 发送，Shift+Enter 换行，@ 提及角色）…',
    ) as HTMLTextAreaElement
    expect(textarea.value).toBe('')
    expect(screen.getByRole('button', { name: '甲追出去解释' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByText('🧭 已选剧情走向')).toBeTruthy()
    expect(sendMessage).not.toHaveBeenCalled()
  })

  it('shows selected directions in a card above the composer and supports multi-select', async () => {
    mockSandboxHistory([{
      instruction: '继续', prose: '他抬起头。',
      suggestions: ['甲追出去解释', '乙干脆离开现场'],
    }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('他抬起头。')
    fireEvent.click(screen.getByRole('button', { name: '甲追出去解释' }))
    fireEvent.click(screen.getByRole('button', { name: '乙干脆离开现场' }))
    const card = screen.getByText('🧭 已选剧情走向').closest('.rounded-lg')!
    expect(card.textContent).toContain('甲追出去解释')
    expect(card.textContent).toContain('乙干脆离开现场')
  })

  it('removes a direction from the card via × and deselects the pill', async () => {
    mockSandboxHistory([{
      instruction: '继续', prose: '他抬起头。',
      suggestions: ['甲追出去解释', '乙干脆离开现场'],
    }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('他抬起头。')
    fireEvent.click(screen.getByRole('button', { name: '甲追出去解释' }))
    fireEvent.click(screen.getByRole('button', { name: '乙干脆离开现场' }))
    fireEvent.click(screen.getByRole('button', { name: '移除 甲追出去解释' }))
    expect(screen.queryByRole('button', { name: '移除 甲追出去解释' })).toBeNull()
    expect(screen.getByRole('button', { name: '移除 乙干脆离开现场' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '甲追出去解释' }).getAttribute('aria-pressed')).toBe('false')
    expect(screen.getByRole('button', { name: '乙干脆离开现场' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('clicking a selected pill again removes it from the composer card', async () => {
    mockSandboxHistory([{
      instruction: '继续', prose: '他抬起头。',
      suggestions: ['甲追出去解释'],
    }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('他抬起头。')
    fireEvent.click(screen.getByRole('button', { name: '甲追出去解释' }))
    expect(screen.getByText('🧭 已选剧情走向')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '甲追出去解释' }))
    expect(screen.queryByText('🧭 已选剧情走向')).toBeNull()
  })

  it('展示已召回记忆卡片，可通过 × 移除', async () => {
    mockSandboxHistory([{ instruction: '继续', prose: '他抬起头。' }])
    const onRemoveMemory = vi.fn()
    renderPanel(
      <StorySandboxPanelHarness
        {...baseProps}
        selectedMemories={[{
          id: 'mem-1', chapter: 3, turnIndex: 1, time: '', location: '',
          characters: [], summary: '旧事件', entities: [], branchId: null,
        }]}
        onRemoveMemory={onRemoveMemory}
      />,
    )
    await screen.findByText('他抬起头。')
    expect(screen.getByText('🧠 已召回记忆')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '移除记忆 mem-1' }))
    expect(onRemoveMemory).toHaveBeenCalledWith('mem-1')
  })

  it('提交时把已召回记忆格式化后拼进发送文本，并调用 onClearMemories', async () => {
    mockSandboxHistory([])
    const sendMessage = vi.fn().mockResolvedValue({ ok: true })
    const onClearMemories = vi.fn()
    renderPanel(
      <StorySandboxPanelHarness
        {...baseProps}
        sendMessage={sendMessage}
        selectedMemories={[{
          id: 'mem-1', chapter: 3, turnIndex: 1, time: '', location: '',
          characters: [], summary: '旧事件', entities: [], branchId: null,
        }]}
        onClearMemories={onClearMemories}
      />,
    )
    const box = await screen.findByPlaceholderText('给导演指令（Enter 发送，Shift+Enter 换行，@ 提及角色）…')
    fireEvent.change(box, { target: { value: '继续写' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    await waitFor(() => expect(sendMessage).toHaveBeenCalled())
    const sentText = sendMessage.mock.calls[0][2] as string
    expect(sentText).toContain('[回忆] 第3章：旧事件')
    expect(sentText).toContain('继续写')
    expect(onClearMemories).toHaveBeenCalled()
  })

  it('clears the composer card after submit', async () => {
    const sendMessage = vi.fn().mockResolvedValue({ ok: true })
    mockSandboxHistory([{
      instruction: '继续', prose: '他抬起头。',
      suggestions: ['甲追出去解释'],
    }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} sendMessage={sendMessage} />)
    await screen.findByText('他抬起头。')
    fireEvent.click(screen.getByRole('button', { name: '甲追出去解释' }))
    const textarea = screen.getByPlaceholderText(
      '给导演指令（Enter 发送，Shift+Enter 换行，@ 提及角色）…',
    ) as HTMLTextAreaElement
    fireEvent.keyDown(textarea, { key: 'Enter' })
    expect(screen.queryByText('🧭 已选剧情走向')).toBeNull()
  })

  it('clears the composer card after deleting the current branch', async () => {
    mockSandboxHistory([{
      instruction: '继续', prose: '他抬起头。',
      suggestions: ['甲追出去解释'],
    }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('他抬起头。')
    fireEvent.click(screen.getByRole('button', { name: '甲追出去解释' }))
    expect(screen.getByText('🧭 已选剧情走向')).toBeTruthy()
    await clickBranchMenuItem('删除当前故事线')
    await screen.findByText(/删除这条故事线/)
    fireEvent.click(screen.getByText('确定'))
    await waitFor(() => {
      expect(screen.queryByText('🧭 已选剧情走向')).toBeNull()
    })
  })

  it('submitting with a selected direction and typed text sends them, then locks the submitted pill', async () => {
    const sendMessage = vi.fn().mockResolvedValue({ ok: true })
    mockSandboxHistory([{
      instruction: '继续', prose: '他抬起头。',
      suggestions: ['甲追出去解释'],
    }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} sendMessage={sendMessage} />)
    await screen.findByText('他抬起头。')
    fireEvent.click(screen.getByText('甲追出去解释'))
    const textarea = screen.getByPlaceholderText(
      '给导演指令（Enter 发送，Shift+Enter 换行，@ 提及角色）…',
    ) as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '再加一点悬念' } })
    fireEvent.keyDown(textarea, { key: 'Enter' })
    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith(
      1, 'b1', '- 甲追出去解释\n\n再加一点悬念', ['甲追出去解释'],
    ))
    expect(
      screen.getByRole('button', { name: /🧭 剧情走向选择.*已提交/ }).getAttribute('data-state'),
    ).toBe('closed')
    fireEvent.click(screen.getByRole('button', { name: /🧭 剧情走向选择/ }))
    const pill = screen.getByRole('button', { name: '甲追出去解释' })
    expect(pill.getAttribute('aria-pressed')).toBe('true')
    expect((pill as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText(/已提交/)).toBeTruthy()
  })

  it('locks the previous round pills immediately on free-text send (no pill clicked)', async () => {
    const sendMessage = vi.fn().mockResolvedValue({ ok: true })
    mockSandboxHistory([{
      instruction: '继续', prose: '他抬起头。',
      suggestions: ['甲追出去解释'],
    }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} sendMessage={sendMessage} />)
    await screen.findByText('他抬起头。')
    const textarea = screen.getByPlaceholderText(
      '给导演指令（Enter 发送，Shift+Enter 换行，@ 提及角色）…',
    ) as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '直接发消息不点选项' } })
    fireEvent.keyDown(textarea, { key: 'Enter' })
    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith(1, 'b1', '直接发消息不点选项', []))
    fireEvent.click(screen.getByRole('button', { name: /🧭 剧情走向选择/ }))
    const pill = screen.getByRole('button', { name: '甲追出去解释' })
    expect((pill as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText(/已提交/)).toBeTruthy()
  })

  it('locks pills from a round that completed live in this session (not REST history)', async () => {
    const sendMessage = vi.fn().mockResolvedValue({ ok: true })
    const store = buildPanelStore()
    const { ws, emit } = makeFakeWs(store)
    wsHolder.current = ws
    mockSandboxHistory([])
    renderWithStore(store, <StorySandboxPanelHarness {...baseProps} sendMessage={sendMessage} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())

    const textarea = screen.getByPlaceholderText(
      '给导演指令（Enter 发送，Shift+Enter 换行，@ 提及角色）…',
    ) as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '开场' } })
    fireEvent.keyDown(textarea, { key: 'Enter' })
    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith(1, 'b1', '开场', []))

    emit({ type: 'story_sandbox_token', delta: '他抬起头。' })
    emit({ type: 'story_sandbox_final', content: '他抬起头。' })
    emit({ type: 'story_sandbox_states', states: {}, scene_state: {} })
    emit({ type: 'story_sandbox_suggestions', options: ['甲追出去解释'] })
    emit({ type: 'story_sandbox_event_log', entries: [], rolling_summary: '' })
    emit({ type: 'story_sandbox_done' })

    await screen.findByText('他抬起头。')
    const pill = await screen.findByRole('button', { name: '甲追出去解释' })
    expect((pill as HTMLButtonElement).disabled).toBe(false)

    fireEvent.change(textarea, { target: { value: '第二段自由文本，不点选项' } })
    fireEvent.keyDown(textarea, { key: 'Enter' })
    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith(1, 'b1', '第二段自由文本，不点选项', []))

    fireEvent.click(screen.getByRole('button', { name: /🧭 剧情走向选择/ }))
    expect((screen.getByRole('button', { name: '甲追出去解释' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('locks pills when sending before story_sandbox_done (suggestions already on liveRound)', async () => {
    const sendMessage = vi.fn().mockResolvedValue({ ok: true })
    const store = buildPanelStore()
    const { ws, emit } = makeFakeWs(store)
    wsHolder.current = ws
    mockSandboxHistory([{ instruction: '继续', prose: '上一段正文。', characterStates: {}, suggestions: [] }])
    renderWithStore(store, <StorySandboxPanelHarness {...baseProps} sendMessage={sendMessage} />)
    await screen.findByText('上一段正文。')

    const textarea = screen.getByPlaceholderText(
      '给导演指令（Enter 发送，Shift+Enter 换行，@ 提及角色）…',
    ) as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '第二段' } })
    fireEvent.keyDown(textarea, { key: 'Enter' })
    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith(1, 'b1', '第二段', []))

    emit({ type: 'story_sandbox_token', delta: '他抬起头。' })
    emit({ type: 'story_sandbox_final', content: '他抬起头。' })
    emit({ type: 'story_sandbox_states', states: {}, scene_state: {} })
    emit({ type: 'story_sandbox_suggestions', options: ['甲追出去解释'] })

    await screen.findByRole('button', { name: '甲追出去解释' })
    expect((screen.getByRole('button', { name: '甲追出去解释' }) as HTMLButtonElement).disabled).toBe(false)

    fireEvent.change(textarea, { target: { value: '不点选项直接发' } })
    fireEvent.keyDown(textarea, { key: 'Enter' })
    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith(1, 'b1', '不点选项直接发', []))

    fireEvent.click(screen.getByRole('button', { name: /🧭 剧情走向选择/ }))
    const pill = screen.getByRole('button', { name: '甲追出去解释' })
    expect((pill as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText(/已提交/)).toBeTruthy()

    emit({ type: 'story_sandbox_event_log', entries: [], rolling_summary: '' })
    emit({ type: 'story_sandbox_done' })
    expect((pill as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows a loading spinner in the prose bubble before the first token, and hides it once streaming starts', async () => {
    // Seeds an existing round so this is NOT the opening turn -- an opening turn's liveRound
    // stays gated behind pendingFields.initialStates (see the "during opening init" test above)
    // and never reaches the prose bubble at all until initial states arrive.
    const sendMessage = vi.fn().mockResolvedValue({ ok: true })
    const store = buildPanelStore()
    const { ws, emit } = makeFakeWs(store)
    wsHolder.current = ws
    mockSandboxHistory([{ instruction: '继续', prose: '他抬起头。' }])
    renderWithStore(store, <StorySandboxPanelHarness {...baseProps} sendMessage={sendMessage} />)
    await screen.findByText('他抬起头。')

    const textarea = screen.getByPlaceholderText(
      '给导演指令（Enter 发送，Shift+Enter 换行，@ 提及角色）…',
    ) as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '第二段指令' } })
    fireEvent.keyDown(textarea, { key: 'Enter' })
    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith(1, 'b1', '第二段指令', []))

    const statusEl = await screen.findByText('思考中…')
    expect(statusEl.parentElement?.querySelector('svg.animate-spin')).toBeTruthy()

    emit({ type: 'story_sandbox_token', delta: '他继续说。' })
    await screen.findByText('他继续说。')
    expect(screen.queryByText('思考中…')).toBeNull()
  })

  it('send button stays enabled (not content-gated) when textarea and selected directions are empty', async () => {
    // ChatComposerBar's single `disabled` prop expresses only inputDisabled (connection/busy/
    // syncing), not "has content" -- when busy the same slot becomes the cancel button, which
    // must stay clickable regardless of input content. Clicking with empty text simply no-ops
    // (submit() early-returns), matching how pressing Enter on an empty textarea already behaved.
    mockSandboxHistory([])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    const sendBtn = screen.getByLabelText('发送') as HTMLButtonElement
    expect(sendBtn.disabled).toBe(false)
  })

  it('typed text and click submits', async () => {
    const sendMessage = vi.fn().mockResolvedValue({ ok: true })
    mockSandboxHistory([])
    renderPanel(<StorySandboxPanelHarness {...baseProps} sendMessage={sendMessage} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    const textarea = screen.getByPlaceholderText(
      '给导演指令（Enter 发送，Shift+Enter 换行，@ 提及角色）…',
    ) as HTMLTextAreaElement
    const sendBtn = screen.getByLabelText('发送') as HTMLButtonElement
    fireEvent.change(textarea, { target: { value: '推进冲突' } })
    fireEvent.click(sendBtn)
    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith(1, 'b1', '推进冲突', []))
  })

  it('send button enables with only a selected direction', async () => {
    mockSandboxHistory([{
      instruction: '继续', prose: '他抬起头。',
      suggestions: ['甲追出去解释'],
    }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('他抬起头。')
    fireEvent.click(screen.getByRole('button', { name: '甲追出去解释' }))
    expect((screen.getByRole('button', { name: '发送' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('empty Enter does not send and does not default to 继续', async () => {
    const sendMessage = vi.fn().mockResolvedValue({ ok: true })
    mockSandboxHistory([])
    renderPanel(<StorySandboxPanelHarness {...baseProps} sendMessage={sendMessage} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    const textarea = screen.getByPlaceholderText(
      '给导演指令（Enter 发送，Shift+Enter 换行，@ 提及角色）…',
    )
    fireEvent.keyDown(textarea, { key: 'Enter' })
    expect(sendMessage).not.toHaveBeenCalled()
  })

  it('展开全部/折叠全部 toggles every round\'s state and suggestions folds at once', async () => {
    mockSandboxHistory([{
      instruction: '继续', prose: '他抬起头。',
      characterStates: { 甲: { psychology: '平静' } },
      suggestions: ['某建议'],
    }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('他抬起头。')

    expect(screen.getByText(/🧬 角色状态（推演）/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('closed')
    expect(screen.getByText(/🧭 剧情走向选择/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('open')

    fireEvent.click(screen.getByRole('button', { name: '展开全部' }))
    expect(screen.getByText(/🧬 角色状态（推演）/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('open')
    expect(screen.getByText(/🧭 剧情走向选择/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('open')

    fireEvent.click(screen.getByRole('button', { name: '折叠全部' }))
    expect(screen.getByText(/🧬 角色状态（推演）/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('closed')
    expect(screen.getByText(/🧭 剧情走向选择/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('closed')
  })

  it('does nothing when the delete-branch confirm dialog is declined', async () => {
    mockSandboxHistory([{ instruction: '你好', prose: '你好呀' }])
    const confirmSpy = vi.spyOn(window, 'confirm')
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('你好呀')
    await clickBranchMenuItem('删除当前故事线')
    await screen.findByText(/删除这条故事线/)
    expect(confirmSpy).not.toHaveBeenCalled() // window.confirm replaced by the toast confirm
    fireEvent.click(screen.getByText('取消'))
    expect(screen.getByText('你好呀')).toBeTruthy()
  })

  it('clears rounds when the delete-branch confirm dialog is accepted and the delete succeeds', async () => {
    const onBranchChange = vi.fn()
    mockSandboxHistory(
      [{ instruction: '你好', prose: '你好呀' }], [],
      { nextBranchAfterDelete: { id: 'b2', name: '故事线2' } },
    )
    renderPanel(<StorySandboxPanelHarness {...baseProps} onBranchChange={onBranchChange} />)
    await screen.findByText('你好呀')
    await clickBranchMenuItem('删除当前故事线')
    await screen.findByText(/删除这条故事线/)
    fireEvent.click(screen.getByText('确定'))
    await waitFor(() => expect(onBranchChange).toHaveBeenCalledWith('b2'))
    await waitFor(() => expect(screen.queryByText('你好呀')).toBeNull())
  })

  it('does nothing when the reset-branch confirm dialog is declined', async () => {
    mockSandboxHistory([{ instruction: '你好', prose: '你好呀' }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('你好呀')
    await clickBranchMenuItem('重置当前故事线')
    await screen.findByText(/重置这条故事线/)
    fireEvent.click(screen.getByText('取消'))
    expect(screen.getByText('你好呀')).toBeTruthy()
  })

  it('clears rounds but keeps the same branch when the reset confirm dialog is accepted', async () => {
    const onBranchChange = vi.fn()
    mockSandboxHistory([{ instruction: '你好', prose: '你好呀' }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} onBranchChange={onBranchChange} />)
    await screen.findByText('你好呀')
    await clickBranchMenuItem('重置当前故事线')
    await screen.findByText(/重置这条故事线/)
    fireEvent.click(screen.getByText('确定'))
    await waitFor(() => expect(screen.queryByText('你好呀')).toBeNull())
    expect(onBranchChange).not.toHaveBeenCalled()
  })

  it('clears the composer card after resetting the current branch', async () => {
    mockSandboxHistory([{
      instruction: '继续', prose: '他抬起头。',
      suggestions: ['甲追出去解释'],
    }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('他抬起头。')
    fireEvent.click(screen.getByRole('button', { name: '甲追出去解释' }))
    expect(screen.getByText('🧭 已选剧情走向')).toBeTruthy()
    await clickBranchMenuItem('重置当前故事线')
    await screen.findByText(/重置这条故事线/)
    fireEvent.click(screen.getByText('确定'))
    await waitFor(() => {
      expect(screen.queryByText('🧭 已选剧情走向')).toBeNull()
    })
  })

  it('invalidates sandbox-memory-archive cache when resetting the current branch', async () => {
    const invalidateSpy = vi.spyOn(QueryClient.prototype, 'invalidateQueries')
    mockSandboxHistory([{ instruction: '你好', prose: '你好呀' }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('你好呀')
    await clickBranchMenuItem('重置当前故事线')
    await screen.findByText(/重置这条故事线/)
    fireEvent.click(screen.getByText('确定'))
    await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['sandbox-memory-archive', 'novel-1', 1],
    }))
  })

  it('invalidates sandbox-memory-archive cache when deleting the current branch', async () => {
    const invalidateSpy = vi.spyOn(QueryClient.prototype, 'invalidateQueries')
    mockSandboxHistory(
      [{ instruction: '你好', prose: '你好呀' }], [],
      { nextBranchAfterDelete: { id: 'b2', name: '故事线2' } },
    )
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('你好呀')
    await clickBranchMenuItem('删除当前故事线')
    await screen.findByText(/删除这条故事线/)
    fireEvent.click(screen.getByText('确定'))
    await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['sandbox-memory-archive', 'novel-1', 1],
    }))
  })

  it('opens a create-branch modal defaulting to "copy from current" and passes source_branch_id', async () => {
    const onBranchChange = vi.fn()
    let createBody: unknown = null
    vi.spyOn(global, 'fetch').mockImplementation(async (url, init) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      if (String(url).includes('/api/story-sandbox/branches') && method === 'GET') {
        return {
          ok: true,
          json: async () => ({ branches: [{ id: 'b1', name: '故事线1', chapter: 1, created_at: '', updated_at: '' }] }),
        } as Response
      }
      if (String(url).includes('/api/story-sandbox/branches') && method === 'POST') {
        createBody = init?.body ? JSON.parse(String(init.body)) : null
        return {
          ok: true,
          json: async () => ({
            ok: true,
            branch: { id: 'b-new', name: '分支线', chapter: 1, created_at: '', updated_at: '' },
          }),
        } as Response
      }
      if (String(url).includes('/api/story-sandbox/history')) {
        return {
          ok: true,
          json: async () => ({
            rounds: [{
              instruction: '你好', prose: '你好呀', character_states: {}, suggestions: [],
              initial_states: null, scene_state: {}, initial_scene_state: null,
            }],
          }),
        } as Response
      }
      return { ok: true, json: async () => ({}) } as Response
    })
    renderPanel(<StorySandboxPanelHarness {...baseProps} onBranchChange={onBranchChange} />)
    await screen.findByText('你好呀')
    await clickBranchMenuItem('新建故事线')
    // Modal opens with the "copy from current" radio checked by default (preserves the old
    // implicit always-inherit behavior), and the current branch's name surfaced in its label.
    expect(await screen.findByText('基于当前故事线「故事线1」复制')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('故事线名称'), { target: { value: '分支线' } })
    fireEvent.click(screen.getByRole('button', { name: '新建' }))
    await waitFor(() => expect(onBranchChange).toHaveBeenCalledWith('b-new'))
    expect(createBody).toMatchObject({ chapter: 1, name: '分支线', source_branch_id: 'b1' })
  })

  it('create-branch modal can be switched to a blank story line instead of copying', async () => {
    const onBranchChange = vi.fn()
    let createBody: unknown = null
    vi.spyOn(global, 'fetch').mockImplementation(async (url, init) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      if (String(url).includes('/api/story-sandbox/branches') && method === 'GET') {
        return {
          ok: true,
          json: async () => ({ branches: [{ id: 'b1', name: '故事线1', chapter: 1, created_at: '', updated_at: '' }] }),
        } as Response
      }
      if (String(url).includes('/api/story-sandbox/branches') && method === 'POST') {
        createBody = init?.body ? JSON.parse(String(init.body)) : null
        return {
          ok: true,
          json: async () => ({
            ok: true,
            branch: { id: 'b-new', name: '空白线', chapter: 1, created_at: '', updated_at: '' },
          }),
        } as Response
      }
      if (String(url).includes('/api/story-sandbox/history')) {
        return {
          ok: true,
          json: async () => ({
            rounds: [{
              instruction: '你好', prose: '你好呀', character_states: {}, suggestions: [],
              initial_states: null, scene_state: {}, initial_scene_state: null,
            }],
          }),
        } as Response
      }
      return { ok: true, json: async () => ({}) } as Response
    })
    renderPanel(<StorySandboxPanelHarness {...baseProps} onBranchChange={onBranchChange} />)
    await screen.findByText('你好呀')
    await clickBranchMenuItem('新建故事线')
    await screen.findByText('新建全新故事线（空白）')
    fireEvent.click(screen.getByText('新建全新故事线（空白）'))
    fireEvent.change(screen.getByLabelText('故事线名称'), { target: { value: '空白线' } })
    fireEvent.click(screen.getByRole('button', { name: '新建' }))
    await waitFor(() => expect(onBranchChange).toHaveBeenCalledWith('b-new'))
    expect(createBody).toEqual({ chapter: 1, name: '空白线' })
  })

  it('surfaces a toast instead of crashing when renaming a branch fails (e.g. branch not found)', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async (url, init) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      if (String(url).includes('/api/story-sandbox/branches/') && method === 'PATCH') {
        return { ok: false, status: 404, json: async () => ({ error: '故事线不存在' }) } as Response
      }
      if (String(url).includes('/api/story-sandbox/branches') && method === 'GET') {
        return {
          ok: true,
          json: async () => ({ branches: [{ id: 'b1', name: '故事线1', chapter: 1, created_at: '', updated_at: '' }] }),
        } as Response
      }
      if (String(url).includes('/api/story-sandbox/history')) {
        return {
          ok: true,
          json: async () => ({
            rounds: [{
              instruction: '你好', prose: '你好呀', character_states: {}, suggestions: [],
              initial_states: null, scene_state: {}, initial_scene_state: null,
            }],
          }),
        } as Response
      }
      return { ok: true, json: async () => ({}) } as Response
    })
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('你好呀')
    await clickBranchMenuItem('重命名')
    const dialog = await screen.findByRole('dialog', { name: '重命名故事线' })
    fireEvent.change(within(dialog).getByLabelText('故事线名称'), { target: { value: '新名字' } })
    fireEvent.click(within(dialog).getByRole('button', { name: '重命名' }))
    expect(await screen.findByText('重命名失败，请重试')).toBeTruthy()
  })

  it('regenerating suggestions shows a pending state, then replaces the last round\'s suggestions on the WS event', async () => {
    const store = buildPanelStore()
    const { ws, emit } = makeFakeWs(store)
    wsHolder.current = ws
    const regenerateSuggestions = vi.fn().mockResolvedValue({ ok: true })
    mockSandboxHistory([{ instruction: '继续', prose: '他抬起头。', suggestions: ['旧建议'] }])
    renderWithStore(
      store, <StorySandboxPanelHarness {...baseProps} regenerateSuggestions={regenerateSuggestions} />,
    )
    await screen.findByText('他抬起头。')
    fireEvent.click(screen.getByRole('button', { name: '重新生成走向' }))
    // Optimistic pending kicks in synchronously -- the bubble (and its old options) swap out for
    // the shared loading placeholder before the ack request even resolves.
    expect(await screen.findByText('正在推演剧情走向…')).toBeTruthy()
    expect(screen.queryByText('旧建议')).toBeNull()
    emit({ type: 'story_sandbox_suggestions_regenerated', options: ['新建议A'] })
    expect(await screen.findByText('新建议A')).toBeTruthy()
    expect(screen.queryByText('旧建议')).toBeNull()
  })

  it('regenerating suggestions with a typed hint forwards it to regenerateSuggestions', async () => {
    const store = buildPanelStore()
    const { ws, emit } = makeFakeWs(store)
    wsHolder.current = ws
    const regenerateSuggestions = vi.fn().mockResolvedValue({ ok: true })
    mockSandboxHistory([{ instruction: '继续', prose: '他抬起头。', suggestions: ['旧建议'] }])
    renderWithStore(
      store, <StorySandboxPanelHarness {...baseProps} regenerateSuggestions={regenerateSuggestions} />,
    )
    await screen.findByText('他抬起头。')
    fireEvent.change(screen.getByPlaceholderText('给重新生成一点提示（可选，/ 选拓展 skill）…'), {
      target: { value: '往乙这边的反应上靠一点' },
    })
    fireEvent.click(screen.getByRole('button', { name: '重新生成走向' }))
    emit({ type: 'story_sandbox_suggestions_regenerated', options: ['新建议A'] })
    await screen.findByText('新建议A')
    expect(regenerateSuggestions).toHaveBeenCalledWith(1, 'b1', '往乙这边的反应上靠一点')
  })

  it('a failed regenerate ack clears the pending state and surfaces a toast', async () => {
    const regenerateSuggestions = vi.fn().mockResolvedValue({ ok: false, error: '有任务运行中' })
    mockSandboxHistory([{ instruction: '继续', prose: '他抬起头。', suggestions: ['旧建议'] }])
    renderPanel(
      <StorySandboxPanelHarness {...baseProps} regenerateSuggestions={regenerateSuggestions} />,
    )
    await screen.findByText('他抬起头。')
    fireEvent.click(screen.getByRole('button', { name: '重新生成走向' }))
    expect(await screen.findByText(/有任务运行中/)).toBeTruthy()
    expect(await screen.findByText('旧建议')).toBeTruthy()
  })

  it('clicking rewrite with typed feedback calls startRewrite without a confirm dialog', async () => {
    const startRewrite = vi.fn().mockResolvedValue({ ok: true })
    mockSandboxHistory([{ instruction: '甲乙对峙', prose: '他抬起头。' }])
    const confirmSpy = vi.spyOn(window, 'confirm')
    renderPanel(<StorySandboxPanelHarness {...baseProps} startRewrite={startRewrite} />)
    await screen.findByText('他抬起头。')
    fireEvent.change(screen.getByPlaceholderText('重写时怎么改（可选）…'), {
      target: { value: '语气再冷淡一点' },
    })
    fireEvent.click(screen.getByRole('button', { name: '重写这段' }))
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(startRewrite).toHaveBeenCalledWith(1, 'b1', '语气再冷淡一点')
  })

  it('输入重写反馈命中已知角色/设定名时显示识别提示行', async () => {
    mockSandboxHistory([{ instruction: '甲乙对峙', prose: '他抬起头。' }])
    renderPanel(
      <StorySandboxPanelHarness
        {...baseProps} characterNames={['李梅']} settingNames={['元气']}
      />,
      { activeNovelId: 'novel-1' },
    )
    await screen.findByText('他抬起头。')
    fireEvent.change(screen.getByPlaceholderText('重写时怎么改（可选）…'), {
      target: { value: '让李梅提一下元气的事' },
    })
    expect(screen.getByText('识别到角色：李梅')).toBeTruthy()
    expect(screen.getByText('识别到设定：元气')).toBeTruthy()
  })

  it('streams rewrite tokens into the latest round in place, then replaces it on done', async () => {
    const startRewrite = vi.fn().mockResolvedValue({ ok: true })
    mockSandboxHistory([{ instruction: '甲乙对峙', prose: '旧正文', suggestions: ['旧建议'] }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} startRewrite={startRewrite} />)
    await screen.findByText('旧正文')
    fireEvent.click(screen.getByRole('button', { name: '重写这段' }))
    await screen.findByRole('button', { name: '重写中…' })
    expect(screen.queryByText('旧正文')).toBeNull()
  })

  it('shows style-guard chip on the historical round during whole-round rewrite', async () => {
    const startRewrite = vi.fn().mockResolvedValue({ ok: true })
    const store = buildPanelStore()
    const { ws, emit } = makeFakeWs(store)
    wsHolder.current = ws
    mockSandboxHistory([{ instruction: '甲乙对峙', prose: '旧正文' }])
    renderWithStore(store, <StorySandboxPanel {...baseProps} startRewrite={startRewrite} />)
    await screen.findByText('旧正文')
    fireEvent.click(screen.getByRole('button', { name: '重写这段' }))
    await screen.findByRole('button', { name: '重写中…' })
    emit({ type: 'story_sandbox_style_rewrite', status: 'start' })
    expect(await screen.findByText('检测到 AI 味文本，正在重写…')).toBeTruthy()
  })

  it('shows style-guard chip on the still-streaming live round during normal turn generation', async () => {
    const store = buildPanelStore()
    const { ws, emit } = makeFakeWs(store)
    wsHolder.current = ws
    mockSandboxHistory([])
    renderWithStore(store, <StorySandboxPanelHarness {...baseProps} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())

    emit({ type: 'story_sandbox_token', delta: '正文' })
    emit({ type: 'story_sandbox_style_rewrite', status: 'start' })
    expect(await screen.findByText('检测到 AI 味文本，正在重写…')).toBeTruthy()
  })

  it('a failed rewrite surfaces an error and leaves the round in place', async () => {
    const startRewrite = vi.fn().mockResolvedValue({ ok: false, error: '上一轮还在进行' })
    mockSandboxHistory([{ instruction: '继续', prose: '他抬起头。' }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} startRewrite={startRewrite} />)
    await screen.findByText('他抬起头。')
    fireEvent.click(screen.getByRole('button', { name: '重写这段' }))
    expect(await screen.findByText(/上一轮还在进行/)).toBeTruthy()
  })

  it('shows retry button only on the last retryable error round', async () => {
    const store = buildPanelStore()
    const { ws, emit } = makeFakeWs(store)
    wsHolder.current = ws
    mockSandboxHistory([{ instruction: '继续', prose: '他抬起头。' }])
    renderWithStore(store, <StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('他抬起头。')

    emit({ type: 'story_sandbox_error', error: '推演失败', code: 'SCENE_DERIVE_FAILED' })
    expect(await screen.findByRole('button', { name: '重试' })).toBeTruthy()

    emit({ type: 'story_sandbox_start', chapter: 1 })
    emit({ type: 'story_sandbox_token', delta: '新一轮正文' })
    emit({ type: 'story_sandbox_final', content: '新一轮正文' })
    emit({ type: 'story_sandbox_states', states: {}, scene_state: {} })
    emit({ type: 'story_sandbox_suggestions', options: [] })
    emit({ type: 'story_sandbox_done' })
    await screen.findByText('新一轮正文')
    expect(screen.queryByRole('button', { name: '重试' })).toBeNull()
  })

  it('clicking retry calls retryDerive with the current chapter/branch', async () => {
    const retryDerive = vi.fn().mockResolvedValue({ ok: true })
    const store = buildPanelStore()
    const { ws, emit } = makeFakeWs(store)
    wsHolder.current = ws
    mockSandboxHistory([{ instruction: '继续', prose: '他抬起头。' }])
    renderWithStore(store, <StorySandboxPanelHarness {...baseProps} retryDerive={retryDerive} />)
    await screen.findByText('他抬起头。')

    emit({ type: 'story_sandbox_error', error: '推演失败', code: 'SCENE_DERIVE_FAILED' })
    fireEvent.click(await screen.findByRole('button', { name: '重试' }))

    await waitFor(() => expect(retryDerive).toHaveBeenCalledWith(1, 'b1'))
  })

  function selectTextInProse(proseEl: HTMLElement, prose: string, needle: string) {
    const textNode = proseEl.querySelector('p')!.firstChild as Text
    const start = prose.indexOf(needle)
    const range = document.createRange()
    range.setStart(textNode, start)
    range.setEnd(textNode, start + needle.length)
    const sel = window.getSelection()!
    sel.removeAllRanges()
    sel.addRange(range)
    return start
  }

  it('queues a selection-rewrite requested while a new turn is streaming/deriving instead of blocking it, and auto-fires it (targeting the original round by id) the moment that turn finishes', async () => {
    const rewriteSelection = vi.fn().mockResolvedValue({ ok: true })
    const store = buildPanelStore()
    const { ws, emit } = makeFakeWs(store)
    wsHolder.current = ws
    const prose = '他抬起头，看向窗外。'
    mockSandboxHistory([{ id: 'round-1', instruction: '继续', prose }])
    renderWithStore(
      store, <StorySandboxPanelHarness {...baseProps} rewriteSelection={rewriteSelection} />,
    )
    await screen.findByText(prose)

    // A new turn starts streaming -- the whole panel is "busy" now, but round-1's own text is
    // already fully rendered and unaffected by it.
    emit({ type: 'story_sandbox_token', delta: '新一轮生成中' })

    const proseEl = screen.getByTestId('prose-content')
    const start = selectTextInProse(proseEl, prose, '看向窗外')
    fireEvent.contextMenu(proseEl)
    fireEvent.click(screen.getByText('重写选中片段'))
    fireEvent.change(screen.getByPlaceholderText('重写时怎么改（可选）…'), {
      target: { value: '语气冷淡一点' },
    })
    fireEvent.click(screen.getByText('重写'))

    expect(await screen.findByText('已排队，将在当前任务完成后重写…')).toBeTruthy()
    expect(rewriteSelection).not.toHaveBeenCalled()

    emit({ type: 'story_sandbox_states', states: {}, scene_state: {} })
    emit({ type: 'story_sandbox_suggestions', options: [], round_id: 'round-new' })
    emit({ type: 'story_sandbox_done' })

    await waitFor(() => expect(rewriteSelection).toHaveBeenCalledWith(
      1, 'b1', '看向窗外', start, '语气冷淡一点', 'round-1',
    ))
  })

  it('shows a jump-to-bottom button after scrolling up during streaming', async () => {
    mockSandboxHistory([{ instruction: '继续', prose: '旧正文' }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('旧正文')
    const scrollEl = document.querySelector('.overflow-y-auto') as HTMLDivElement
    Object.defineProperties(scrollEl, {
      scrollHeight: { value: 1000, configurable: true },
      scrollTop: { value: 0, writable: true, configurable: true },
      clientHeight: { value: 100, configurable: true },
    })
    fireEvent.scroll(scrollEl)
    expect(await screen.findByText('跳转至底部')).toBeTruthy()
  })

  it('sending a message flips the composer button into cancel mode, and clicking it calls stopTurn', async () => {
    const sendMessage = vi.fn().mockResolvedValue({ ok: true })
    const stopTurn = vi.fn().mockResolvedValue({ ok: true })
    mockSandboxHistory([])
    renderPanel(<StorySandboxPanelHarness {...baseProps} sendMessage={sendMessage} stopTurn={stopTurn} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    fireEvent.change(screen.getByPlaceholderText(/给导演指令/), { target: { value: '继续写' } })
    fireEvent.click(screen.getByLabelText('发送'))
    await waitFor(() => expect(screen.getByLabelText('中断')).toBeTruthy())
    fireEvent.click(screen.getByLabelText('中断'))
    await waitFor(() => expect(stopTurn).toHaveBeenCalledWith(1, 'b1'))
  })

  it('receiving story_sandbox_turn_cancelled restores the submitted text into the input and clears busy', async () => {
    const sendMessage = vi.fn().mockResolvedValue({ ok: true })
    const store = buildPanelStore()
    const { ws, emit } = makeFakeWs(store)
    wsHolder.current = ws
    mockSandboxHistory([])
    renderWithStore(store, <StorySandboxPanelHarness {...baseProps} sendMessage={sendMessage} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    fireEvent.change(screen.getByPlaceholderText(/给导演指令/), { target: { value: '被中断的指令' } })
    fireEvent.click(screen.getByLabelText('发送'))
    await waitFor(() => expect(screen.getByLabelText('中断')).toBeTruthy())
    emit({ type: 'story_sandbox_turn_cancelled', chapter: 1, rollback_failed: false })
    await waitFor(() => expect(screen.getByLabelText('发送')).toBeTruthy())
    expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty('value', '被中断的指令')
  })

  it('draft persists across scope switch: novel/chapter A draft does not leak into B, and A keeps its own on switch-back', async () => {
    mockSandboxHistory([])
    const { rerender } = renderPanel(<StorySandboxPanelHarness {...baseProps} novelId="novelA" selectedChapter={1} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())

    fireEvent.change(screen.getByPlaceholderText(/给导演指令/), { target: { value: 'A的草稿' } })
    await waitFor(() => expect(sessionStorage.getItem('story-sandbox-draft:novelA:1')).toBe('A的草稿'))

    rerender(<><StorySandboxPanelHarness {...baseProps} novelId="novelB" selectedChapter={1} /><ToasterHost /></>)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty('value', '')

    rerender(<><StorySandboxPanelHarness {...baseProps} novelId="novelA" selectedChapter={1} /><ToasterHost /></>)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty('value', 'A的草稿')
  })

  it('auto-fills the composer with location + description on a fresh chapter with no draft, and shows a toast', async () => {
    mockSandboxHistory(
      [], [{ stage_num: 1, description: '甲乙在书房对峙', location: '书房' }],
    )
    renderPanel(<StorySandboxPanelHarness {...baseProps} novelId="novelA" selectedChapter={1} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    await waitFor(() => expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty(
      'value', '地点：书房\n\n剧情：甲乙在书房对峙',
    ))
    expect(screen.getByText('已自动填入本章 stage1 大纲，可编辑后发送')).toBeTruthy()
  })

  it('auto-fills with an empty location line when stage1 has no location set', async () => {
    mockSandboxHistory([], [{ stage_num: 1, description: '甲乙在书房对峙' }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} novelId="novelA" selectedChapter={1} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    await waitFor(() => expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty(
      'value', '地点：\n\n剧情：甲乙在书房对峙',
    ))
  })

  it('does not overwrite an existing draft with stage1 outline', async () => {
    mockSandboxHistory([], [{ stage_num: 1, description: '甲乙在书房对峙' }])
    sessionStorage.setItem('story-sandbox-draft:novelA:1', '我自己写的开场')
    renderPanel(<StorySandboxPanelHarness {...baseProps} novelId="novelA" selectedChapter={1} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty('value', '我自己写的开场')
  })

  it('does not auto-fill once the chapter already has rounds', async () => {
    mockSandboxHistory(
      [{ instruction: '继续', prose: '他抬起头。' }],
      [{ stage_num: 1, description: '甲乙在书房对峙' }],
    )
    renderPanel(<StorySandboxPanelHarness {...baseProps} novelId="novelA" selectedChapter={1} />)
    await screen.findByText('他抬起头。')
    expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty('value', '')
  })

  it('does not re-fill the composer on a refresh mid-generation (0 persisted rounds, but a live round in flight)', async () => {
    // Reproduces: user sends the opening turn (input cleared to '', draft persisted as ''), then
    // refreshes the page while the turn is still generating -- historyRounds is still [] (the
    // turn hasn't been persisted into `rounds` yet), so the prefill effect must key off
    // history.liveRound instead of rounds.length to know a turn is already running.
    sessionStorage.setItem('story-sandbox-draft:novelA:1', '')
    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      if (String(url).includes('/api/story-sandbox/history')) {
        return {
          ok: true,
          json: async () => ({
            rounds: [],
            live_round: { mode: 'turn', instruction: '甲乙在书房对峙', events: [] },
          }),
        } as Response
      }
      if (String(url).includes('/api/setup/skeleton/')) {
        return {
          ok: true,
          json: async () => ({
            chapter: 0, exists: true,
            stages: [{ stage_num: 1, description: '甲乙在书房对峙', beats: [], expanded: false }],
          }),
        } as Response
      }
      return { ok: true, json: async () => ({}) } as Response
    })
    renderPanel(<StorySandboxPanelHarness {...baseProps} novelId="novelA" selectedChapter={1} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty('value', '')
  })

  it('does not re-paste the stage1 outline after leaving and reopening the sandbox tab while the opening turn is still initializing character state', async () => {
    // Reproduces a real bug: submitting the opening turn clears the composer and persists an
    // empty ('') draft to sessionStorage. Switching to another tab (对话/设定) and back fully
    // unmounts and remounts this panel; the remount's history query can still be serving its
    // pre-submit cached response (rounds: [], no live_round) for a moment -- e.g. while the
    // opening turn is deriving initial character state, before the query cache catches up. The
    // prefill effect must not mistake that already-cleared '' draft for "no draft ever saved"
    // and re-paste the stage1 outline into the still-disabled composer.
    mockSandboxHistory([], [{ stage_num: 1, description: '甲乙在书房对峙' }])
    const sendMessage = vi.fn().mockResolvedValue({ ok: true })
    const { rerender } = renderPanel(
      <StorySandboxPanelHarness
        {...baseProps} novelId="novelA" selectedChapter={1} sendMessage={sendMessage}
      />,
    )
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    await waitFor(() => (
      expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty(
        'value', '地点：\n\n剧情：甲乙在书房对峙',
      )
    ))

    fireEvent.click(screen.getByLabelText('发送'))
    await waitFor(() => expect(sendMessage).toHaveBeenCalled())
    await waitFor(() => expect(sessionStorage.getItem('story-sandbox-draft:novelA:1')).toBe(''))

    // Simulate switching away to another tab and back: the panel unmounts (local state lost)
    // then remounts, while the underlying query cache still reflects the pre-submit response
    // (the same "hasn't caught up yet" window the mid-generation-refresh test covers via a
    // stale-but-present history.liveRound race, just triggered by remount instead of refresh).
    rerender(<><div /><ToasterHost /></>)
    rerender(
      <>
        <StorySandboxPanelHarness
          {...baseProps} novelId="novelA" selectedChapter={1} sendMessage={sendMessage}
        />
        <ToasterHost />
      </>,
    )

    expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty('value', '')
  })

  it('a novel with no prior mode selection defaults to free mode with the composer already enabled', async () => {
    renderPanel(<StorySandboxPanelHarness {...baseProps} novelId="novel-fresh" />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(false)
    expect(screen.getByRole('button', { name: '切换自由/章节模式' }).textContent).toBe('自由')
  })

  it('chapter dropdown only renders in chapter mode (the branch dropdown renders in both)', async () => {
    renderPanel(<StorySandboxPanelHarness {...baseProps} novelId="novel-fresh" />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    // Free mode: only the branch dropdown.
    expect(screen.getAllByRole('combobox')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: '切换自由/章节模式' }))
    // Chapter mode: chapter dropdown + branch dropdown.
    expect(screen.getAllByRole('combobox')).toHaveLength(2)
  })

  it('mode toggle is never locked, even once the active thread has history', async () => {
    mockSandboxHistory([{ instruction: '继续', prose: '他抬起头。' }])
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await screen.findByText('他抬起头。')
    expect((screen.getByRole('button', { name: '切换自由/章节模式' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('switching chapter/free mode always starts the composer blank, even after leaving unsent text in a mode visited earlier this session', async () => {
    renderPanel(<StorySandboxPanelHarness {...baseProps} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    // starts in chapter mode (novel-1 defaults to 'chapter' per beforeEach)
    const toggle = () => screen.getByRole('button', { name: '切换自由/章节模式' })
    fireEvent.change(screen.getByPlaceholderText(/给导演指令/), { target: { value: '章节模式里没发送的草稿' } })

    fireEvent.click(toggle())
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    expect(toggle().textContent).toBe('自由')
    expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty('value', '')

    fireEvent.change(screen.getByPlaceholderText(/给导演指令/), { target: { value: '自由模式里没发送的草稿' } })
    // Switching back to chapter mode must not resurrect the draft left behind above -- a manual
    // mode toggle always reads as a fresh start, unlike a tab-switch/reload remount.
    fireEvent.click(toggle())
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    expect(toggle().textContent).toBe('章节')
    expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty('value', '')

    fireEvent.click(toggle())
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    expect(toggle().textContent).toBe('自由')
    expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty('value', '')
  })

  it('mode selection persists across remount for the same novel this session', async () => {
    const { unmount } = renderPanel(<StorySandboxPanelHarness {...baseProps} novelId="novel-fresh" />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    // novel-fresh defaults to free mode; toggle to chapter and confirm that sticks across remount
    // instead of resetting back to the default.
    fireEvent.click(screen.getByRole('button', { name: '切换自由/章节模式' }))
    await waitFor(() => expect(screen.getAllByRole('combobox')).toHaveLength(2))
    unmount()

    renderPanel(<StorySandboxPanelHarness {...baseProps} novelId="novel-fresh" />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())
    // Still chapter mode, not reset to free -- chapter dropdown + branch dropdown both show.
    expect(screen.getAllByRole('combobox')).toHaveLength(2)
  })

  it('invalidates sandboxCastArchives on profile_mutation, done, and rewrite_done WS events', async () => {
    const invalidateSpy = vi.spyOn(QueryClient.prototype, 'invalidateQueries')
    const store = buildPanelStore()
    const { ws, emit } = makeFakeWs(store)
    wsHolder.current = ws
    mockSandboxHistory([])
    renderWithStore(store, <StorySandboxPanelHarness {...baseProps} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())

    emit({ type: 'story_sandbox_profile_mutation', mutation: { 甲: { race: '精灵' } } })
    await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['sandboxCastArchives', 'novel-1', 1],
    }))

    invalidateSpy.mockClear()
    emit({ type: 'story_sandbox_token', delta: '正文' })
    emit({ type: 'story_sandbox_done' })
    // story_sandbox_history's react-query (and its invalidation) has been retired -- Redux's
    // sandboxSlice.chat is fed directly by wsEventReceived, live, so there's no cache left to
    // invalidate here. sandboxCastArchives is a separate, still-react-query-backed feature.
    await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['sandboxCastArchives', 'novel-1', 1],
    }))

    invalidateSpy.mockClear()
    emit({
      type: 'story_sandbox_rewrite_done',
      content: '新正文',
      suggestions: [],
      states: {},
      scene_state: {},
      recall_context: '',
      recalled_settings: [],
      entries: [],
      rolling_summary: '',
      mutation: null,
    })
    await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['sandboxCastArchives', 'novel-1', 1],
    }))

    invalidateSpy.mockRestore()
  })

  it('invalidates sandbox-memory-archive on done and rewrite_done, but not on profile_mutation alone', async () => {
    const invalidateSpy = vi.spyOn(QueryClient.prototype, 'invalidateQueries')
    const store = buildPanelStore()
    const { ws, emit } = makeFakeWs(store)
    wsHolder.current = ws
    mockSandboxHistory([])
    renderWithStore(store, <StorySandboxPanelHarness {...baseProps} />)
    await waitFor(() => expect(screen.queryByText(CHAT_HISTORY_SYNC_LABEL)).toBeNull())

    emit({ type: 'story_sandbox_profile_mutation', mutation: { 甲: { race: '精灵' } } })
    await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['sandboxCastArchives', 'novel-1', 1],
    }))
    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['sandbox-memory-archive', 'novel-1', 1],
    })

    invalidateSpy.mockClear()
    emit({ type: 'story_sandbox_token', delta: '正文' })
    emit({ type: 'story_sandbox_done' })
    await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['sandbox-memory-archive', 'novel-1', 1],
    }))

    invalidateSpy.mockClear()
    emit({
      type: 'story_sandbox_rewrite_done',
      content: '新正文',
      suggestions: [],
      states: {},
      scene_state: {},
      recall_context: '',
      recalled_settings: [],
      entries: [],
      rolling_summary: '',
      mutation: null,
    })
    await waitFor(() => expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['sandbox-memory-archive', 'novel-1', 1],
    }))

    invalidateSpy.mockRestore()
  })

// The old "events arriving while history is syncing get queued locally and replayed in order
// after the snapshot lands" guarantee was specific to the retired react-query + local pendingSync
// -EventsRef design. In the current design, live wsEventReceived events are folded into
// sandboxSlice.chat immediately and unconditionally (see the slice's extraReducers), regardless
// of whether hydrateSandboxChat's own REST fetch is still in flight for this scope -- the same
// characteristic authorLoopSlice's hydrateAuthorLoop already has (its own hydrateCleared/replay
// unconditionally resets state before folding in the REST-provided event log). A narrow race is
// possible if a live event arrives strictly between hydrateSandboxChat's fetch resolving and its
// hydrateSeeded/liveSeeded reducers running, since those reset chat before replaying the REST
// snapshot's own events -- but that window is a single REST round-trip, not the (up to 30s)
// react-query staleness window the sandbox-remount bug this migration fixes actually had, and
// matches the accepted precedent. Not covered by a dedicated regression test here.

  it('characterNames 传入后，打 @ 弹出候选下拉', async () => {
    const { getByRole, findByRole } = renderPanel(
      <StorySandboxPanelHarness {...baseProps} characterNames={['橘花音', '苏晚晴']} />,
      { activeNovelId: 'novel-1' },
    )
    const textarea = getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '@' } })
    textarea.setSelectionRange(1, 1)
    fireEvent.select(textarea)
    const listbox = await findByRole('listbox')
    expect(listbox.textContent).toContain('橘花音')
    expect(listbox.textContent).toContain('苏晚晴')
  })

  it('输入文本命中已知角色名时，输入框下方显示"识别到角色"提示行', () => {
    const { getByRole, getByText } = renderPanel(
      <StorySandboxPanelHarness {...baseProps} characterNames={['橘花音', '苏晚晴']} />,
      { activeNovelId: 'novel-1' },
    )
    const textarea = getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '橘花音去便利店' } })
    expect(getByText('识别到角色：橘花音')).toBeTruthy()
  })

  it('不传 characterNames 时不显示识别提示行（回归：默认值不报错）', () => {
    const { getByRole, queryByText } = renderPanel(
      <StorySandboxPanelHarness {...baseProps} />, { activeNovelId: 'novel-1' },
    )
    const textarea = getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '随便写点什么' } })
    expect(queryByText(/识别到角色/)).toBeNull()
  })

  it('输入文本命中已知设定名时，输入框下方显示"识别到设定"提示行', () => {
    const { getByRole, getByText } = renderPanel(
      <StorySandboxPanelHarness {...baseProps} settingNames={['元气', '元素']} />,
      { activeNovelId: 'novel-1' },
    )
    const textarea = getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '元气开始运转' } })
    expect(getByText('识别到设定：元气')).toBeTruthy()
  })

  it('不传 settingNames 时不显示"识别到设定"提示行（回归：默认值不报错）', () => {
    const { getByRole, queryByText } = renderPanel(
      <StorySandboxPanelHarness {...baseProps} />, { activeNovelId: 'novel-1' },
    )
    const textarea = getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '随便写点什么' } })
    expect(queryByText(/识别到设定/)).toBeNull()
  })

  it('选中剧情走向 pill 后（不重新手输），识别提示行也覆盖 pill 里提到的角色/设定', async () => {
    mockSandboxHistory([{
      instruction: '继续', prose: '他抬起头。',
      suggestions: ['李梅走向元气泉水'],
    }])
    renderPanel(
      <StorySandboxPanelHarness
        {...baseProps} characterNames={['李梅']} settingNames={['元气']}
      />,
      { activeNovelId: 'novel-1' },
    )
    await screen.findByText('他抬起头。')
    fireEvent.click(screen.getByRole('button', { name: '李梅走向元气泉水' }))
    expect(screen.getByText('识别到角色：李梅')).toBeTruthy()
    expect(screen.getByText('识别到设定：元气')).toBeTruthy()
  })

  it('characterNames + settingNames 合并进 @ 候选，各自带类型标签', async () => {
    const { getByRole, findAllByRole } = renderPanel(
      <StorySandboxPanelHarness
        {...baseProps} characterNames={['李梅']} settingNames={['元气']}
      />,
      { activeNovelId: 'novel-1' },
    )
    const textarea = getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '@' } })
    textarea.setSelectionRange(1, 1)
    fireEvent.select(textarea)
    const options = await findAllByRole('option')
    expect(options.length).toBeGreaterThanOrEqual(2)
    expect(options.map((o) => o.textContent).join(' ')).toContain('李梅')
    expect(options.map((o) => o.textContent).join(' ')).toContain('角色')
    expect(options.map((o) => o.textContent).join(' ')).toContain('元气')
    expect(options.map((o) => o.textContent).join(' ')).toContain('设定')
  })

  it('@ 候选较多时，下拉列表仍完整渲染全部选项（不被底部输入区 overflow 裁切）', async () => {
    const names = Array.from({ length: 10 }, (_, i) => `角色${i + 1}`)
    const { getByRole, findAllByRole } = renderPanel(
      <StorySandboxPanelHarness {...baseProps} characterNames={names} />,
      { activeNovelId: 'novel-1' },
    )
    const textarea = getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '@' } })
    textarea.setSelectionRange(1, 1)
    fireEvent.select(textarea)
    const options = await findAllByRole('option')
    expect(options).toHaveLength(10)
    expect(options.map((o) => o.textContent?.replace(/角色$/, ''))).toEqual(names)
  })

  describe('↑/↓ 翻历史发言', () => {
    it('聚焦空输入框按 ↑ 两次依次加载最新、次新的历史指令', async () => {
      mockSandboxHistory([
        { instruction: '第一条指令', prose: '很久以前……' },
        { instruction: '第二条指令', prose: '后来……' },
      ])
      renderPanel(<StorySandboxPanelHarness {...baseProps} />)
      await screen.findByText('第二条指令')

      const box = screen.getByPlaceholderText(/给导演指令/) as HTMLTextAreaElement
      box.focus()
      box.setSelectionRange(0, 0)
      fireEvent.keyDown(box, { key: 'ArrowUp' })
      expect(box.value).toBe('第二条指令')
      box.setSelectionRange(box.value.length, box.value.length)
      fireEvent.keyDown(box, { key: 'ArrowUp' })
      expect(box.value).toBe('第一条指令')
    })
  })
})

describe('buildSubmissionText', () => {
  it('拼接已选剧情走向与手输内容', () => {
    expect(buildSubmissionText('手输内容', ['走向A', '走向B'])).toBe('- 走向A\n- 走向B\n\n手输内容')
  })

  it('只有已选走向、没有手输内容时不留多余空行', () => {
    expect(buildSubmissionText('', ['走向A'])).toBe('- 走向A')
  })

  it('只有手输内容、没有已选走向时原样返回', () => {
    expect(buildSubmissionText('手输内容', [])).toBe('手输内容')
  })

  it('两者都为空返回空字符串', () => {
    expect(buildSubmissionText('', [])).toBe('')
  })
})
