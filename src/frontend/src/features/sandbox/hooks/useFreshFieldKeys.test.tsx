import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useFreshFieldKeys } from '@/features/sandbox/hooks/useFreshFieldKeys'

describe('useFreshFieldKeys', () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }))
  afterEach(() => vi.useRealTimers())

  it('returns an empty set when there is no mutation', () => {
    const { result } = renderHook(() => useFreshFieldKeys(undefined))
    expect(result.current).toEqual(new Set())
  })

  it('returns the mutation field keys while within the TTL window', () => {
    const { result } = renderHook(() => useFreshFieldKeys({ fields: { race: '精灵' }, at: Date.now() }))
    expect(result.current).toEqual(new Set(['race']))
  })

  it('clears automatically once the TTL elapses', async () => {
    const at = Date.now()
    const { result } = renderHook(() => useFreshFieldKeys({ fields: { race: '精灵' }, at }, 5000))
    expect(result.current).toEqual(new Set(['race']))
    await act(async () => { await vi.advanceTimersByTimeAsync(5001) })
    expect(result.current).toEqual(new Set())
  })

  it('is already empty for a mutation whose timestamp is already past the TTL', () => {
    const { result } = renderHook(() => useFreshFieldKeys({ fields: { race: '精灵' }, at: Date.now() - 6000 }, 5000))
    expect(result.current).toEqual(new Set())
  })
})
