import type { CharacterState, Round } from '@/features/sandbox/hooks/useStorySandbox'
import type { RelationshipEdge } from '@/shared/types'
import type { EventLogEntry, StorySandboxEvent } from '@/features/sandbox/utils/storySandboxHistory'
import {
  clearAllDerivationsPending,
  clearDerivationPending,
  markDerivationsPending,
  type PendingDerivations,
} from '@/features/sandbox/utils/sandboxDeriveFields'

export type LiveRound = {
  /** Stable round id, stamped on once story_sandbox_suggestions arrives (see reduceStorySandboxEvent
   * -- the backend's "suggest" node is what actually appends this round) so it's already present
   * by the time story_sandbox_done folds this liveRound into `rounds`. Absent before that. */
  id?: string
  instruction: string
  prose: string
  characterStates: Record<string, CharacterState>
  suggestions: string[]
  initialStates: Record<string, CharacterState> | null
  sceneState: Record<string, unknown>
  initialSceneState: Record<string, unknown> | null
  eventLogEntries: EventLogEntry[]
  rollingSummaryAfter: string
  recallContext: string
  recalledSettings: { category: string; name: string; desc: string }[]
  profileMutation: Record<string, Record<string, unknown>> | null
  relationshipMutation: Record<string, RelationshipEdge> | null
}

export type PendingSelectionRewrite = {
  roundId: string
  originalText: string
  anchorOffset: number
  feedback: string
}

export type ChatState = {
  rounds: Round[]
  liveRound: LiveRound | null
  status: string
  rewritingProse: string | null
  styleRewriting: boolean
  selectionRewriting: boolean
  /** Which round's context-menu rewrite is in flight right now -- drives the per-round "正在
   * 重写…" indicator instead of always lighting up the last round, now that the menu is unlocked
   * on every completed round regardless of what's currently streaming. Undefined/null while none
   * is in flight (including for callers that predate this field). */
  selectionRewritingRoundId?: string | null
  /** Selected fragment + anchor for in-place loading UI while selectionRewriting is true. */
  selectionRewritingAnchor?: { originalText: string; anchorOffset: number } | null
  /** A selection-rewrite request made while another story_sandbox_* task was already busy --
   * held here instead of being rejected, and auto-fired once busy clears (see
   * StorySandboxPanel's queued-selection-rewrite effect). Only one slot: a second attempt while
   * one is already queued replaces it rather than stacking (see handleRewriteSelection). */
  pendingSelectionRewrite?: PendingSelectionRewrite | null
  /** True while a directed profile/relationship mutation rewrite is in flight. */
  profileMutationRewriting?: boolean
  pendingFields: PendingDerivations
}

export const EMPTY_LIVE_ROUND: LiveRound = {
  instruction: '', prose: '', characterStates: {}, suggestions: [], initialStates: null,
  sceneState: {}, initialSceneState: null, eventLogEntries: [], rollingSummaryAfter: '',
  recallContext: '', recalledSettings: [], profileMutation: null, relationshipMutation: null,
}

export const EMPTY_CHAT_STATE: ChatState = {
  rounds: [], liveRound: null, status: '', rewritingProse: null, styleRewriting: false,
  selectionRewriting: false, pendingFields: {},
}

// Pure function: the ONLY place that knows about story_sandbox_* WS event shapes. Updates
// liveRound/rounds only -- never renders. Mirrors SetupChatPanel.tsx's reduceChatEvent shape,
// but keeps protocol parsing fully separate from the TurnSegments rendering layer.
export function reduceStorySandboxEvent(s: ChatState, ev: StorySandboxEvent): ChatState {
  switch (ev.type) {
    case 'story_sandbox_token': {
      const prev = s.liveRound ?? EMPTY_LIVE_ROUND
      return { ...s, liveRound: { ...prev, prose: prev.prose + ev.delta }, status: '' }
    }
    case 'story_sandbox_final': {
      const prev = s.liveRound ?? EMPTY_LIVE_ROUND
      return {
        ...s,
        liveRound: { ...prev, prose: ev.content },
        status: '',
        // Prose is final -> character-state derivation starts next; mark it pending until
        // story_sandbox_states arrives (there's no separate "derivation started" event).
        pendingFields: markDerivationsPending(s.pendingFields, ['characterStates', 'sceneState']),
      }
    }
    case 'story_sandbox_initial_states': {
      const prev = s.liveRound ?? EMPTY_LIVE_ROUND
      let pendingFields = clearDerivationPending(s.pendingFields, 'initialStates')
      pendingFields = clearDerivationPending(pendingFields, 'initialSceneState')
      return {
        ...s,
        liveRound: { ...prev, initialStates: ev.states, initialSceneState: ev.scene_state },
        pendingFields,
      }
    }
    case 'story_sandbox_suggestions': {
      // The rewrite path broadcasts this same event type while rewritingProse is active and
      // liveRound is null -- only touch liveRound for a normal turn, or this would spawn a
      // phantom empty-prose liveRound that renders as an extra box until rewrite_done clears it.
      if (s.rewritingProse !== null) {
        return { ...s, pendingFields: clearDerivationPending(s.pendingFields, 'suggestions') }
      }
      const prev = s.liveRound ?? EMPTY_LIVE_ROUND
      return {
        ...s,
        // round_id: the "suggest" node is what appends this turn's round on the backend, so this
        // is the first (and only) event carrying its stable id -- stamping it onto liveRound here
        // means it's already present by the time story_sandbox_done folds liveRound into rounds.
        liveRound: { ...prev, suggestions: ev.options, id: ev.round_id ?? prev.id },
        pendingFields: clearDerivationPending(s.pendingFields, 'suggestions'),
      }
    }
    case 'story_sandbox_suggestions_regenerated': {
      const pendingFields = clearDerivationPending(s.pendingFields, 'suggestions')
      if (s.rounds.length === 0) return { ...s, pendingFields }
      const rounds = [...s.rounds]
      rounds[rounds.length - 1] = { ...rounds[rounds.length - 1], suggestions: ev.options }
      return { ...s, rounds, pendingFields }
    }
    case 'story_sandbox_suggestions_regenerate_error':
      return { ...s, pendingFields: clearDerivationPending(s.pendingFields, 'suggestions') }
    case 'story_sandbox_states': {
      // Suggestions derivation starts next -- mark it pending in the same step that clears
      // characterStates, since both arrive on this one event.
      const nextPending = markDerivationsPending(
        clearDerivationPending(clearDerivationPending(s.pendingFields, 'characterStates'), 'sceneState'),
        ['suggestions'],
      )
      // Same rewrite guard as story_sandbox_suggestions above -- don't spawn a phantom liveRound.
      if (s.rewritingProse !== null) {
        return { ...s, pendingFields: nextPending }
      }
      const prev = s.liveRound ?? EMPTY_LIVE_ROUND
      return {
        ...s,
        liveRound: { ...prev, characterStates: ev.states, sceneState: ev.scene_state },
        pendingFields: nextPending,
      }
    }
    case 'story_sandbox_event_log': {
      // Rolling summary updates every round regardless of whether this round produced its own
      // event entry -- don't skip the update just because ev.entry is null.
      if (s.rewritingProse !== null) return s
      const prev = s.liveRound ?? EMPTY_LIVE_ROUND
      return {
        ...s,
        liveRound: { ...prev, eventLogEntries: ev.entries, rollingSummaryAfter: ev.rolling_summary },
      }
    }
    case 'story_sandbox_profile_mutation': {
      if (s.rewritingProse !== null) return s
      const prev = s.liveRound ?? EMPTY_LIVE_ROUND
      return { ...s, liveRound: { ...prev, profileMutation: ev.mutation } }
    }
    case 'story_sandbox_profile_mutation_rewriting':
      return { ...s, profileMutationRewriting: true }
    case 'story_sandbox_profile_mutation_rewrite_done': {
      const idx = ev.round_index
      const applyToRound = (round: Round): Round => ({
        ...round,
        profileMutation: ev.profile_mutation,
        relationshipMutation: ev.relationship_mutation,
      })
      if (s.liveRound && idx === s.rounds.length) {
        const prev = s.liveRound
        return {
          ...s,
          profileMutationRewriting: false,
          liveRound: {
            ...prev,
            profileMutation: ev.profile_mutation,
            relationshipMutation: ev.relationship_mutation,
          },
        }
      }
      if (idx < 0 || idx >= s.rounds.length) {
        return { ...s, profileMutationRewriting: false }
      }
      const rounds = [...s.rounds]
      rounds[idx] = applyToRound(rounds[idx])
      return { ...s, profileMutationRewriting: false, rounds }
    }
    case 'story_sandbox_profile_mutation_rewrite_error':
      return { ...s, profileMutationRewriting: false }
    case 'story_sandbox_recall_context': {
      if (s.rewritingProse !== null) return s
      const prev = s.liveRound ?? EMPTY_LIVE_ROUND
      return {
        ...s,
        liveRound: { ...prev, recallContext: ev.recall_context, recalledSettings: ev.recalled_settings },
      }
    }
    case 'story_sandbox_error':
      return {
        ...s,
        pendingFields: clearAllDerivationsPending(),
        rounds: [...s.rounds, {
          instruction: s.liveRound?.instruction ?? '', prose: `⚠️ ${ev.error}`,
          characterStates: {}, suggestions: [], initialStates: null,
          sceneState: {}, initialSceneState: null, eventLogEntries: [],
          ...(ev.code ? { errorCode: ev.code } : {}),
        }],
        liveRound: null,
        rewritingProse: null,
        styleRewriting: false,
        status: '',
      }
    case 'story_sandbox_done':
      if (!s.liveRound) {
        return { ...s, status: '', styleRewriting: false, pendingFields: clearAllDerivationsPending() }
      }
      // User may send the next instruction while this turn's tail events are still running;
      // lockSuggestionsBeforeSend already folded the completed turn into `rounds`, leaving a
      // fresh liveRound shell (instruction only, no prose yet) for the new turn.
      if (!s.liveRound.prose.trim()) {
        return {
          ...s,
          status: '',
          styleRewriting: false,
          pendingFields: clearAllDerivationsPending(),
        }
      }
      return {
        ...s,
        rounds: [...s.rounds, s.liveRound],
        liveRound: null,
        status: '',
        styleRewriting: false,
        pendingFields: clearAllDerivationsPending(),
      }
    case 'story_sandbox_turn_cancelled':
      return {
        ...s,
        liveRound: null,
        rewritingProse: null,
        status: '',
        styleRewriting: false,
        pendingFields: clearAllDerivationsPending(),
      }
    case 'story_sandbox_style_rewrite':
      return { ...s, styleRewriting: ev.status === 'start' }
    case 'story_sandbox_rewrite_token':
      return { ...s, rewritingProse: (s.rewritingProse ?? '') + ev.delta }
    case 'story_sandbox_rewrite_done': {
      const cleared = {
        rewritingProse: null,
        liveRound: null,
        styleRewriting: false,
        pendingFields: clearAllDerivationsPending(),
      }
      if (s.rounds.length === 0) return { ...s, ...cleared }
      const rounds = [...s.rounds]
      const last = rounds[rounds.length - 1]
      rounds[rounds.length - 1] = {
        ...last,
        prose: ev.content,
        characterStates: ev.states ?? last.characterStates ?? {},
        suggestions: ev.suggestions ?? last.suggestions ?? [],
        sceneState: ev.scene_state ?? last.sceneState ?? {},
        recallContext: ev.recall_context ?? last.recallContext ?? '',
        recalledSettings: ev.recalled_settings ?? last.recalledSettings ?? [],
        eventLogEntries: ev.entries ?? [],
        rollingSummaryAfter: ev.rolling_summary ?? last.rollingSummaryAfter ?? '',
        profileMutation: ev.mutation ?? null,
        relationshipMutation: ev.relationship_mutation ?? last.relationshipMutation ?? null,
      }
      return { ...s, ...cleared, rounds }
    }
    case 'story_sandbox_selection_rewrite_start':
      return { ...s, selectionRewriting: true, selectionRewritingRoundId: ev.round_id ?? null }
    case 'story_sandbox_selection_rewrite_done': {
      if (s.rounds.length === 0) {
        return {
          ...s,
          selectionRewriting: false,
          selectionRewritingRoundId: null,
          selectionRewritingAnchor: null,
        }
      }
      // Target by round_id, not always "the last round" -- a request queued while busy (see
      // handleRewriteSelection) can fire after a newer round has since been appended, so the
      // round it was made against may no longer be last. Falls back to the last round when
      // round_id is absent (older/queue-less callers -- there's only ever one round to mean then).
      const idx = ev.round_id ? s.rounds.findIndex((r) => r.id === ev.round_id) : s.rounds.length - 1
      if (idx < 0) {
        return {
          ...s,
          selectionRewriting: false,
          selectionRewritingRoundId: null,
          selectionRewritingAnchor: null,
        }
      }
      const rounds = [...s.rounds]
      rounds[idx] = { ...rounds[idx], prose: ev.content }
      return {
        ...s,
        rounds,
        selectionRewriting: false,
        selectionRewritingRoundId: null,
        selectionRewritingAnchor: null,
      }
    }
    case 'story_sandbox_selection_rewrite_error':
      return {
        ...s,
        selectionRewriting: false,
        selectionRewritingRoundId: null,
        selectionRewritingAnchor: null,
      }
    default:
      return s
  }
}

/** Lock suggestion pills on any round still open when a send happens, regardless of whether
 * the user actually picked options from it -- sending starts a new turn either way, so a
 * previous round's pills must stop being clickable, not just the ones that were picked. */
export function lockRoundSuggestions(rounds: Round[], submitted: string[]): Round[] {
  return rounds.map((r) => {
    if (r.suggestions.length === 0 || r.suggestionsLocked) return r
    const picked = submitted.filter((d) => r.suggestions.includes(d))
    return { ...r, submittedDirections: picked, suggestionsLocked: true }
  })
}

function liveRoundHasPendingDerivations(pendingFields: PendingDerivations): boolean {
  return !!(
    pendingFields.characterStates
    || pendingFields.sceneState
    || pendingFields.suggestions
    || pendingFields.initialStates
    || pendingFields.initialSceneState
  )
}

/** True once suggestion pills have landed and no derive fields are pending — the director may
 * pick a pill or type the next instruction even if event_log / story_sandbox_done are still in
 * flight. Requires suggestions on liveRound so prose still streaming stays busy. */
export function isSandboxDirectorInputReady(chat: ChatState): boolean {
  const live = chat.liveRound
  if (!live?.prose.trim() || live.suggestions.length === 0) return false
  return !liveRoundHasPendingDerivations(chat.pendingFields)
}

/** Mirrors StorySandboxPanel's composer busy gate — kept here so submit locking and UI agree. */
export function isSandboxComposerBusy(chat: ChatState): boolean {
  if (chat.rewritingProse !== null || chat.selectionRewriting || chat.profileMutationRewriting) return true
  if (isSandboxDirectorInputReady(chat)) return false
  if (chat.liveRound !== null) return true
  return chat.status !== ''
}

function liveRoundToRound(live: LiveRound): Round {
  return {
    instruction: live.instruction,
    prose: live.prose,
    characterStates: live.characterStates,
    suggestions: live.suggestions,
    initialStates: live.initialStates,
    sceneState: live.sceneState,
    initialSceneState: live.initialSceneState,
    eventLogEntries: live.eventLogEntries,
    rollingSummaryAfter: live.rollingSummaryAfter,
    recallContext: live.recallContext,
    recalledSettings: live.recalledSettings,
    profileMutation: live.profileMutation,
    relationshipMutation: live.relationshipMutation,
    id: live.id,
  }
}

/** Lock every still-open suggestion group before starting the next turn. Rounds in history are
 * updated in place; a completed turn still sitting on liveRound (director-input window before
 * story_sandbox_done) is folded into rounds as locked so pills don't stay clickable. */
export function lockSuggestionsBeforeSend(chat: ChatState, submitted: string[]): Round[] {
  let rounds = lockRoundSuggestions(chat.rounds, submitted)
  const live = chat.liveRound
  if (live && live.suggestions.length > 0 && live.prose.trim()) {
    const picked = submitted.filter((d) => live.suggestions.includes(d))
    rounds = [
      ...rounds,
      { ...liveRoundToRound(live), submittedDirections: picked, suggestionsLocked: true },
    ]
  }
  return rounds
}

/** Historical rounds before the latest are not editable; only the tail stays open. */
export function lockHistoricalRoundSuggestions(rounds: Round[]): Round[] {
  return rounds.map((r, i) => (
    i < rounds.length - 1 && r.suggestions.length > 0
      ? { ...r, suggestionsLocked: true }
      : r
  ))
}

/** Reconcile a freshly fetched REST snapshot against what the client already knows, without ever
 * letting it regress local state. suggestionsLocked/submittedDirections are a pure client-side
 * overlay -- the REST history endpoint has no concept of them, it just returns turns positionally
 * -- so a fetch is only safe to apply wholesale when it's caught up. A round's own `story_sandbox_
 * done` invalidates this query, but that fetch can resolve *after* a later round has already
 * completed locally (e.g. queued behind the backend's event loop while that later round's turn
 * runs) while still only reflecting the earlier data: shorter than what's already rendered. Taking
 * it at face value would silently drop the newer round and un-lock the one before it. */
export function mergeRestRounds(prevRounds: Round[], freshRounds: Round[]): Round[] {
  if (freshRounds.length < prevRounds.length) return prevRounds
  return freshRounds.map((r, i) => (prevRounds[i]?.suggestionsLocked ? prevRounds[i] : r))
}
