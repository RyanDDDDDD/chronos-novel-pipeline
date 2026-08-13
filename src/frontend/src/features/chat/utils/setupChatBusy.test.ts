import { describe, it, expect } from 'vitest'
import { reduceSetupChatBusy } from './setupChatBusy'

describe('reduceSetupChatBusy', () => {
  it('locks on in-flight events', () => {
    expect(reduceSetupChatBusy(false, { type: 'setup_chat_token' })).toBe(true)
    expect(reduceSetupChatBusy(false, { type: 'setup_chat_tool' })).toBe(true)
  })

  it('unlocks on terminal events', () => {
    expect(reduceSetupChatBusy(true, { type: 'setup_chat_done' })).toBe(false)
    expect(reduceSetupChatBusy(true, { type: 'setup_chat_error' })).toBe(false)
  })

  it('ignores unrelated events', () => {
    expect(reduceSetupChatBusy(true, { type: 'author_loop_done' })).toBe(true)
    expect(reduceSetupChatBusy(false, { type: 'token_usage' })).toBe(false)
  })

  it('setup_chat_turn_cancelled clears busy, same as done/error', () => {
    expect(reduceSetupChatBusy(true, { type: 'setup_chat_turn_cancelled' })).toBe(false)
  })

  it('setup_chat_queued does not change busy', () => {
    expect(reduceSetupChatBusy(true, { type: 'setup_chat_queued' })).toBe(true)
    expect(reduceSetupChatBusy(false, { type: 'setup_chat_queued' })).toBe(false)
  })
})
