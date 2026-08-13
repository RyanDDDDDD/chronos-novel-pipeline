import { useEffect, useRef, useState } from 'react'

export const NEAR_BOTTOM_PX = 96
export const NEAR_TOP_PX = 96

export function isNearBottom(el: HTMLElement, threshold = NEAR_BOTTOM_PX): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold
}

export function isNearTop(el: HTMLElement, threshold = NEAR_TOP_PX): boolean {
  return el.scrollTop <= threshold
}

function scrollElementToBottom(el: HTMLElement, behavior: ScrollBehavior = 'smooth') {
  if (typeof el.scrollTo === 'function') {
    el.scrollTo({ top: el.scrollHeight, behavior })
  } else {
    el.scrollTop = el.scrollHeight
  }
}

function scrollElementToTop(el: HTMLElement, behavior: ScrollBehavior = 'smooth') {
  if (typeof el.scrollTo === 'function') {
    el.scrollTo({ top: 0, behavior })
  } else {
    el.scrollTop = 0
  }
}

/** Follow chat scroll only while the user is already near the bottom; otherwise keep their
 * scroll position and expose a jump-to-bottom affordance. When content grows while scrolled
 * up, hasNewContentBelow flips true so the button can hint that WS/streaming appended text. */
export function useChatScrollFollow(scrollTrigger: string, resetKey?: string | number) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)
  const prevTriggerRef = useRef(scrollTrigger)
  const [showScrollToBottom, setShowScrollToBottom] = useState(false)
  const [hasNewContentBelow, setHasNewContentBelow] = useState(false)
  const [showScrollToTop, setShowScrollToTop] = useState(false)

  const syncStickState = () => {
    const el = scrollRef.current
    if (!el) return
    const near = isNearBottom(el)
    stickToBottomRef.current = near
    setShowScrollToBottom(!near)
    if (near) setHasNewContentBelow(false)
    setShowScrollToTop(!isNearTop(el))
  }

  const handleScroll = () => syncStickState()

  const scrollToBottom = () => {
    const el = scrollRef.current
    if (!el) return
    stickToBottomRef.current = true
    scrollElementToBottom(el)
    setShowScrollToBottom(false)
    setHasNewContentBelow(false)
    setShowScrollToTop(!isNearTop(el))
  }

  const scrollToTop = () => {
    const el = scrollRef.current
    if (!el) return
    stickToBottomRef.current = false
    scrollElementToTop(el)
    setShowScrollToTop(false)
  }

  useEffect(() => {
    stickToBottomRef.current = true
    prevTriggerRef.current = scrollTrigger
    setShowScrollToBottom(false)
    setHasNewContentBelow(false)
    setShowScrollToTop(false)
  }, [resetKey])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const triggerChanged = prevTriggerRef.current !== scrollTrigger
    prevTriggerRef.current = scrollTrigger
    if (stickToBottomRef.current) {
      scrollElementToBottom(el, 'auto')
      setShowScrollToBottom((v) => (v ? false : v))
      setHasNewContentBelow((v) => (v ? false : v))
      const nearTop = isNearTop(el)
      setShowScrollToTop((v) => {
        const next = !nearTop
        return v === next ? v : next
      })
      return
    }
    if (triggerChanged) setHasNewContentBelow(true)
    syncStickState()
  }, [scrollTrigger])

  return {
    scrollRef, handleScroll, showScrollToBottom, hasNewContentBelow, scrollToBottom,
    showScrollToTop, scrollToTop,
  }
}
