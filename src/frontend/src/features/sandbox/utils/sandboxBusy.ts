const TERMINAL_EVENT_TYPES = new Set([
  'story_sandbox_done', 'story_sandbox_error',
  'story_sandbox_turn_cancelled', 'story_sandbox_rewrite_done',
  'story_sandbox_suggestions_regenerated', 'story_sandbox_suggestions_regenerate_error',
  'story_sandbox_selection_rewrite_done', 'story_sandbox_selection_rewrite_error',
  'story_sandbox_profile_mutation_rewrite_done', 'story_sandbox_profile_mutation_rewrite_error',
])

/** Infer "processing" lock based on story_sandbox WS events -- mirrors reduceSetupChatBusy. */
export function reduceSandboxBusy(busy: boolean, ev: { type: string }): boolean {
  if (TERMINAL_EVENT_TYPES.has(ev.type)) return false
  if (ev.type.startsWith('story_sandbox_')) return true
  return busy
}
