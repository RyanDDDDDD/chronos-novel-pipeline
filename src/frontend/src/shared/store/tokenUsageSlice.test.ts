import { describe, it, expect } from 'vitest'
import tokenUsageReducer, { selectTokenUsage, tokenUsageKey, clearTokenUsage } from '@/shared/store/tokenUsageSlice'
import { wsEventReceived } from '@/shared/store/wsActions'

describe('tokenUsageSlice', () => {
  it('starts empty', () => {
    expect(tokenUsageReducer(undefined, { type: '@@INIT' })).toEqual({})
  })

  it('token_usage event records a cell keyed by subsystem:key', () => {
    const state = tokenUsageReducer(
      {},
      wsEventReceived({
        type: 'token_usage', subsystem: 'author_loop', key: '3',
        tokens_in: 100, tokens_out: 50, tokens_cached: 10,
      }),
    )
    expect(state[tokenUsageKey('author_loop', '3')]).toEqual({
      tokens_in: 100, tokens_out: 50, tokens_cached: 10,
    })
  })

  it('token_usage event without subsystem or key is a no-op', () => {
    const state = tokenUsageReducer({}, wsEventReceived({ type: 'token_usage' }))
    expect(state).toEqual({})
  })

  it('falls back to input/output/cached aliases when tokens_in/out/cached are absent', () => {
    const state = tokenUsageReducer(
      {},
      wsEventReceived({ type: 'token_usage', subsystem: 'setup_chat', key: 'world', input: 5, output: 6, cached: 1 }),
    )
    expect(state[tokenUsageKey('setup_chat', 'world')]).toEqual({
      tokens_in: 5, tokens_out: 6, tokens_cached: 1,
    })
  })

  it('selectTokenUsage(subsystem, key) reads a stored cell, null when absent', () => {
    const cell = { tokens_in: 1, tokens_out: 2, tokens_cached: 0 }
    const state = { tokenUsage: { [tokenUsageKey('author_loop', '3')]: cell } }
    expect(selectTokenUsage('author_loop', '3')(state as never)).toEqual(cell)
    expect(selectTokenUsage('author_loop', '4')(state as never)).toBeNull()
  })

  it('clearTokenUsage empties the map', () => {
    const prev = { [tokenUsageKey('a', 'b')]: { tokens_in: 1, tokens_out: 1, tokens_cached: 0 } }
    expect(tokenUsageReducer(prev, clearTokenUsage())).toEqual({})
  })
})
