/** @vitest-environment jsdom */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { isNearBottom, isNearTop, useChatScrollFollow } from './useChatScrollFollow'

describe('isNearBottom', () => {
  it('returns true when scrolled to the bottom', () => {
    const el = { scrollHeight: 1000, scrollTop: 900, clientHeight: 100 } as HTMLElement
    expect(isNearBottom(el)).toBe(true)
  })

  it('returns false when far from the bottom', () => {
    const el = { scrollHeight: 1000, scrollTop: 0, clientHeight: 100 } as HTMLElement
    expect(isNearBottom(el)).toBe(false)
  })
})

describe('isNearTop', () => {
  it('returns true when scrolled to the top', () => {
    const el = { scrollHeight: 1000, scrollTop: 0, clientHeight: 100 } as HTMLElement
    expect(isNearTop(el)).toBe(true)
  })

  it('returns false when far from the top', () => {
    const el = { scrollHeight: 1000, scrollTop: 900, clientHeight: 100 } as HTMLElement
    expect(isNearTop(el)).toBe(false)
  })
})

describe('useChatScrollFollow', () => {
  beforeEach(() => {
    vi.stubGlobal('scrollTo', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('does not auto-scroll when the user has scrolled away from the bottom', () => {
    const scrollTo = vi.fn()
    const el = document.createElement('div')
    Object.defineProperties(el, {
      scrollHeight: { value: 1000, configurable: true },
      scrollTop: { value: 0, writable: true, configurable: true },
      clientHeight: { value: 100, configurable: true },
      scrollTo: { value: scrollTo, configurable: true },
    })

    const { result, rerender } = renderHook(
      ({ trigger }) => {
        const hook = useChatScrollFollow(trigger, 'k')
        hook.scrollRef.current = el
        return hook
      },
      { initialProps: { trigger: '0' } },
    )

    act(() => result.current.handleScroll())
    expect(result.current.showScrollToBottom).toBe(true)
    scrollTo.mockClear()

    rerender({ trigger: '1' })
    expect(scrollTo).not.toHaveBeenCalled()
    expect(result.current.showScrollToBottom).toBe(true)
    expect(result.current.hasNewContentBelow).toBe(true)
  })

  it('clears hasNewContentBelow after scrollToBottom', () => {
    const scrollTo = vi.fn()
    const el = document.createElement('div')
    Object.defineProperties(el, {
      scrollHeight: { value: 800, configurable: true },
      scrollTop: { value: 0, writable: true, configurable: true },
      clientHeight: { value: 100, configurable: true },
      scrollTo: { value: scrollTo, configurable: true },
    })

    const { result } = renderHook(() => {
      const hook = useChatScrollFollow('0', 'k')
      hook.scrollRef.current = el
      return hook
    })

    act(() => result.current.handleScroll())
    expect(result.current.showScrollToBottom).toBe(true)

    act(() => result.current.scrollToBottom())
    expect(scrollTo).toHaveBeenCalledWith({ top: 800, behavior: 'smooth' })
    expect(result.current.showScrollToBottom).toBe(false)
    expect(result.current.hasNewContentBelow).toBe(false)
  })

  it('shows the scroll-to-top button once scrolled away from the top, and clears it on scrollToTop', () => {
    const scrollTo = vi.fn()
    const el = document.createElement('div')
    Object.defineProperties(el, {
      scrollHeight: { value: 1000, writable: true, configurable: true },
      scrollTop: { value: 900, writable: true, configurable: true },
      clientHeight: { value: 100, configurable: true },
      scrollTo: { value: scrollTo, configurable: true },
    })

    const { result } = renderHook(() => {
      const hook = useChatScrollFollow('0', 'k')
      hook.scrollRef.current = el
      return hook
    })

    act(() => result.current.handleScroll())
    expect(result.current.showScrollToTop).toBe(true)

    act(() => result.current.scrollToTop())
    expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' })
    expect(result.current.showScrollToTop).toBe(false)
  })
})
