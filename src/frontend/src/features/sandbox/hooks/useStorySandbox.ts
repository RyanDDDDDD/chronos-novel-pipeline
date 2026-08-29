import { useCallback } from 'react'
import { fetchStorySandboxHistory, type EventLogEntry } from '@/features/sandbox/utils/storySandboxHistory'

export type CharacterState = Record<string, unknown>
export type SceneState = Record<string, unknown>
export type Round = {
  /** Stable per-round identity assigned by the backend once the round is fully appended --
   * absent on a still-streaming liveRound until its story_sandbox_suggestions event arrives (see
   * reduceStorySandboxEvent), and on rounds persisted before this field shipped. Lets
   * selection-rewrite target this exact round even after later rounds get appended, including a
   * request queued while busy and fired once it clears (see sandboxSelectionRewriteQueue). */
  id?: string
  instruction: string
  prose: string
  characterStates: Record<string, CharacterState>
  suggestions: string[]
  initialStates?: Record<string, CharacterState> | null
  sceneState: SceneState
  initialSceneState?: SceneState | null
  /** Directions the user picked from this round's pills when they sent the next message. */
  submittedDirections?: string[]
  /** When true, pills are collapsed, disabled, and show submittedDirections styling only. */
  suggestionsLocked?: boolean
  /** Keyword-triggered event-recall entries logged for this round (0..N). */
  eventLogEntries: EventLogEntry[]
  /** rolling_summary snapshot right after this round's own fold. */
  rollingSummaryAfter?: string
  /** recall_relevant_context(instruction) result captured at prose-write time for this round;
   * always a string ('' when nothing was recalled, never absent). */
  recallContext?: string
  /** Named world-bible entries (factions/geography/races/power_system) recalled for this round --
   * a structured subset of recallContext's text, kept separately so the UI can highlight setting
   * hits distinctly from event-log history. Always an array, empty when nothing matched. */
  recalledSettings?: { category: string; name: string; desc: string }[]
  /** Session-local character-profile mutation for this round (sliders/physique/gender/race/
   * personality/identity_background/hobbies/verbal_tic), or null when this round produced none. */
  profileMutation?: Record<string, Record<string, unknown>> | null
  /** Session-local relationship-graph-edge proposals for this round ("from→to" -> edge), or null. */
  relationshipMutation?: Record<string, import('@/shared/types').RelationshipEdge> | null
  /** Present on error rounds folded from story_sandbox_error when the backend supplied a
   * DerivationValidationError code -- drives the retry-derive button in StorySandboxPanel. */
  errorCode?: string
  /** URL of the generated scene image for this round, merged in by StorySandboxPanel from a
   * separate /api/story-sandbox/scene-images fetch (not part of the LangGraph turn state). */
  sceneImageUrl?: string
}

/** Network calls for the story-sandbox feature: kept deliberately separate from the large
 * useOrchestrator hook since this feature is independent of author_loop/setup_chat. */
export function useStorySandbox() {
  const sendMessage = useCallback(
    async (
      chapter: number, branchId: string, text: string, submittedDirections?: string[],
    ): Promise<{ ok: boolean; error?: string }> => {
      try {
        const body: { chapter: number; branch_id: string; text: string; submitted_directions?: string[] } =
          { chapter, branch_id: branchId, text }
        if (submittedDirections && submittedDirections.length > 0) {
          body.submitted_directions = submittedDirections
        }
        const res = await fetch('/api/story-sandbox/message', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        const resBody = await res.json().catch(() => ({}))
        if (!res.ok) {
          return { ok: false, error: (resBody as { error?: string }).error ?? `发送失败 (HTTP ${res.status})` }
        }
        return { ok: true }
      } catch {
        return { ok: false, error: '无法连接后端' }
      }
    },
    [],
  )

  const stopTurn = useCallback(
    async (chapter: number, branchId: string): Promise<{ ok: boolean; error?: string }> => {
      try {
        const res = await fetch('/api/story-sandbox/stop', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chapter, branch_id: branchId }),
        })
        const body = await res.json().catch(() => ({}))
        if (!res.ok) {
          return { ok: false, error: (body as { error?: string }).error ?? `中断失败 (HTTP ${res.status})` }
        }
        return { ok: true }
      } catch {
        return { ok: false, error: '无法连接后端' }
      }
    },
    [],
  )

  const fetchHistory = useCallback(
    (chapter: number, branchId: string, novelId: string) => fetchStorySandboxHistory(chapter, branchId, novelId),
    [],
  )

  const regenerateSuggestions = useCallback(
    async (chapter: number, branchId: string, hint = ''): Promise<{ ok: boolean; error?: string }> => {
      try {
        const res = await fetch('/api/story-sandbox/suggestions/regenerate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chapter, branch_id: branchId, hint }),
        })
        const body = await res.json().catch(() => ({}))
        if (!res.ok) {
          return { ok: false, error: (body as { error?: string }).error ?? `重新生成失败 (HTTP ${res.status})` }
        }
        return { ok: true }
      } catch {
        return { ok: false, error: '无法连接后端' }
      }
    },
    [],
  )

  const startRewrite = useCallback(
    async (chapter: number, branchId: string, feedback: string): Promise<{ ok: boolean; error?: string }> => {
      try {
        const res = await fetch('/api/story-sandbox/rewrite', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chapter, branch_id: branchId, feedback }),
        })
        const body = await res.json().catch(() => ({}))
        if (!res.ok) {
          return { ok: false, error: (body as { error?: string }).error ?? `重写失败 (HTTP ${res.status})` }
        }
        return { ok: true }
      } catch {
        return { ok: false, error: '无法连接后端' }
      }
    },
    [],
  )

  const rewriteSelection = useCallback(
    async (
      chapter: number, branchId: string, originalText: string, anchorOffset: number, feedback: string,
      roundId?: string,
    ): Promise<{ ok: boolean; error?: string }> => {
      try {
        const res = await fetch('/api/story-sandbox/rewrite-selection', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            chapter, branch_id: branchId, original_text: originalText, anchor_offset: anchorOffset, feedback,
            round_id: roundId,
          }),
        })
        const body = await res.json().catch(() => ({}))
        if (!res.ok) {
          return { ok: false, error: (body as { error?: string }).error ?? `重写失败 (HTTP ${res.status})` }
        }
        return { ok: true }
      } catch {
        return { ok: false, error: '无法连接后端' }
      }
    },
    [],
  )

  const retryDerive = useCallback(
    async (chapter: number, branchId: string): Promise<{ ok: boolean; error?: string }> => {
      try {
        const res = await fetch('/api/story-sandbox/retry-derive', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chapter, branch_id: branchId }),
        })
        const body = await res.json().catch(() => ({}))
        if (!res.ok) {
          return { ok: false, error: (body as { error?: string }).error ?? `重试失败 (HTTP ${res.status})` }
        }
        return { ok: true }
      } catch {
        return { ok: false, error: '无法连接后端' }
      }
    },
    [],
  )

  const rewriteProfileMutation = useCallback(
    async (chapter: number, branchId: string, feedback: string): Promise<{ ok: boolean; error?: string }> => {
      try {
        const res = await fetch('/api/story-sandbox/profile-mutate/rewrite', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chapter, branch_id: branchId, feedback }),
        })
        const body = await res.json().catch(() => ({}))
        if (!res.ok) {
          return { ok: false, error: (body as { error?: string }).error ?? `重写失败 (HTTP ${res.status})` }
        }
        return { ok: true }
      } catch {
        return { ok: false, error: '无法连接后端' }
      }
    },
    [],
  )

  return {
    sendMessage, stopTurn, fetchHistory, regenerateSuggestions, startRewrite,
    rewriteSelection, retryDerive, rewriteProfileMutation,
  }
}
