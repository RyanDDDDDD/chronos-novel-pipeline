import { describe, it, expect } from 'vitest'
import { reduceSandboxBusy } from './sandboxBusy'

describe('reduceSandboxBusy', () => {
  it('locks on in-flight events', () => {
    expect(reduceSandboxBusy(false, { type: 'story_sandbox_token' })).toBe(true)
    expect(reduceSandboxBusy(false, { type: 'story_sandbox_states' })).toBe(true)
  })

  it('locks on suggestions-regenerate start, the one-shot call with no streaming step', () => {
    expect(reduceSandboxBusy(false, { type: 'story_sandbox_suggestions_regenerating' })).toBe(true)
  })

  it('unlocks on terminal events', () => {
    expect(reduceSandboxBusy(true, { type: 'story_sandbox_done' })).toBe(false)
    expect(reduceSandboxBusy(true, { type: 'story_sandbox_error' })).toBe(false)
    expect(reduceSandboxBusy(true, { type: 'story_sandbox_rewrite_done' })).toBe(false)
    expect(reduceSandboxBusy(true, { type: 'story_sandbox_suggestions_regenerated' })).toBe(false)
    expect(reduceSandboxBusy(true, { type: 'story_sandbox_suggestions_regenerate_error' })).toBe(false)
  })

  it('ignores unrelated events', () => {
    expect(reduceSandboxBusy(true, { type: 'setup_chat_done' })).toBe(true)
    expect(reduceSandboxBusy(false, { type: 'token_usage' })).toBe(false)
  })

  it('story_sandbox_turn_cancelled clears busy, same as done/error', () => {
    expect(reduceSandboxBusy(true, { type: 'story_sandbox_turn_cancelled' })).toBe(false)
  })

  it('locks on selection-rewrite start and unlocks on its terminal events', () => {
    expect(reduceSandboxBusy(false, { type: 'story_sandbox_selection_rewrite_start' })).toBe(true)
    expect(reduceSandboxBusy(true, { type: 'story_sandbox_selection_rewrite_done' })).toBe(false)
    expect(reduceSandboxBusy(true, { type: 'story_sandbox_selection_rewrite_error' })).toBe(false)
  })
})
