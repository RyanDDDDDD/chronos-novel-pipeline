import type { CharacterState, Round } from '@/features/sandbox/hooks/useStorySandbox'
import { inferSubmittedDirections } from '@/features/sandbox/utils/reconstructSubmittedDirections'

import type { EventLogEntry } from '@/shared/types'

export type { EventLogEntry }

export function mapRoundEventLogEntries(
  r: { event_log_entries?: EventLogEntry[]; event_log_entry?: EventLogEntry | null },
): EventLogEntry[] {
  if (Array.isArray(r.event_log_entries)) {
    return r.event_log_entries.filter((e) => Boolean(e?.summary))
  }
  if (r.event_log_entry?.summary) return [r.event_log_entry]
  return []
}

export type StorySandboxEvent =
  | { type: 'story_sandbox_token'; delta: string }
  | { type: 'story_sandbox_final'; content: string }
  | { type: 'story_sandbox_initial_states'; states: Record<string, CharacterState>; scene_state: Record<string, unknown> }
  | { type: 'story_sandbox_suggestions'; options: string[]; round_id?: string }
  | { type: 'story_sandbox_suggestions_regenerating' }
  | { type: 'story_sandbox_suggestions_regenerated'; options: string[] }
  | { type: 'story_sandbox_suggestions_regenerate_error'; error: string }
  | { type: 'story_sandbox_states'; states: Record<string, CharacterState>; scene_state: Record<string, unknown> }
  | {
      type: 'story_sandbox_event_log'
      entries: EventLogEntry[]
      rolling_summary: string
    }
  | { type: 'story_sandbox_profile_mutation'; mutation: Record<string, Record<string, unknown>> | null }
  | {
      type: 'story_sandbox_profile_mutation_rewrite_done'
      round_index: number
      profile_mutation: Record<string, Record<string, unknown>> | null
      relationship_mutation: Record<string, import('@/shared/types').RelationshipEdge> | null
    }
  | { type: 'story_sandbox_profile_mutation_rewrite_error'; error: string }
  | { type: 'story_sandbox_profile_mutation_rewriting' }
  | {
      type: 'story_sandbox_recall_context'
      recall_context: string
      recalled_settings: { category: string; name: string; desc: string }[]
    }
  | { type: 'story_sandbox_error'; error: string; code?: string }
  | { type: 'story_sandbox_done' }
  | { type: 'story_sandbox_turn_cancelled'; chapter: number; rollback_failed: boolean }
  | { type: 'story_sandbox_style_rewrite'; status: 'start' | 'end' }
  | { type: 'story_sandbox_rewrite_token'; delta: string }
  | {
      type: 'story_sandbox_rewrite_done'
      content: string
      suggestions: string[]
      states: Record<string, CharacterState>
      scene_state: Record<string, unknown>
      recall_context: string
      recalled_settings: { category: string; name: string; desc: string }[]
      entries: EventLogEntry[]
      rolling_summary: string
      mutation: Record<string, Record<string, unknown>> | null
      relationship_mutation?: Record<string, import('@/shared/types').RelationshipEdge> | null
    }
  | { type: 'story_sandbox_selection_rewrite_start'; round_id?: string }
  | { type: 'story_sandbox_selection_rewrite_done'; content: string; round_id?: string }
  | { type: 'story_sandbox_selection_rewrite_error'; error: string; round_id?: string }

export type StorySandboxHistory = {
  rounds: Round[]
  active_cast: string[]
  liveRound: {
    mode: 'turn' | 'rewrite' | 'suggestions_regenerate' | 'selection_rewrite' | 'profile_mutation_rewrite'
    instruction: string
    events: StorySandboxEvent[]
  } | null
}

export async function fetchStorySandboxHistory(
  chapter: number,
  branchId: string,
  novelId: string,
): Promise<StorySandboxHistory> {
  if (!novelId || !branchId) return { rounds: [], active_cast: [], liveRound: null }
  try {
    const params = new URLSearchParams({
      chapter: String(chapter),
      branch_id: branchId,
      novel_id: novelId,
    })
    const res = await fetch(`/api/story-sandbox/history?${params}`)
    const body = await res.json().catch(() => ({}))
    const rawRounds = Array.isArray((body as { rounds?: unknown[] }).rounds)
      ? (body as {
          rounds: {
            id?: string
            instruction?: string; prose: string
            character_states?: Record<string, CharacterState>; suggestions?: string[]
            initial_states?: Record<string, CharacterState> | null
            submitted_directions?: string[] | null
            scene_state?: Record<string, unknown>
            initial_scene_state?: Record<string, unknown> | null
            event_log_entries?: EventLogEntry[]
            event_log_entry?: EventLogEntry | null
            rolling_summary_after?: string
            recall_context?: string
            recalled_settings?: { category: string; name: string; desc: string }[]
            profile_mutation?: Record<string, Record<string, unknown>> | null
            relationship_mutation?: Record<string, import('@/shared/types').RelationshipEdge> | null
          }[]
        }).rounds
      : []
    const activeCast = Array.isArray((body as { active_cast?: unknown }).active_cast)
      ? (body as { active_cast: string[] }).active_cast
      : []
    const rawLive = (body as { live_round?: unknown }).live_round
    const rawMode = (rawLive as { mode?: string } | undefined)?.mode
    const liveMode: 'turn' | 'rewrite' | 'suggestions_regenerate' | 'selection_rewrite' | 'profile_mutation_rewrite' =
      rawMode === 'rewrite' || rawMode === 'suggestions_regenerate' || rawMode === 'selection_rewrite'
        || rawMode === 'profile_mutation_rewrite'
        ? rawMode : 'turn'
    const liveRound = rawLive && typeof rawLive === 'object'
      ? {
          mode: liveMode,
          instruction: (rawLive as { instruction?: string }).instruction ?? '',
          events: Array.isArray((rawLive as { events?: unknown[] }).events)
            ? (rawLive as { events: StorySandboxEvent[] }).events
            : [],
        }
      : null

    return {
      rounds: inferSubmittedDirections(rawRounds.map((r) => ({
        id: r.id ?? undefined,
        instruction: r.instruction ?? '', prose: r.prose,
        characterStates: r.character_states ?? {}, suggestions: r.suggestions ?? [],
        initialStates: r.initial_states ?? null,
        submittedDirections: r.submitted_directions ?? undefined,
        sceneState: r.scene_state ?? {},
        initialSceneState: r.initial_scene_state ?? null,
        eventLogEntries: mapRoundEventLogEntries(r),
        rollingSummaryAfter: r.rolling_summary_after ?? '',
        recallContext: r.recall_context ?? '',
        recalledSettings: r.recalled_settings ?? [],
        profileMutation: r.profile_mutation ?? null,
        relationshipMutation: r.relationship_mutation ?? null,
      }))),
      active_cast: activeCast,
      liveRound,
    }
  } catch {
    return { rounds: [], active_cast: [], liveRound: null }
  }
}
