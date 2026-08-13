// @vitest-environment jsdom
// wsMiddleware.ts reads window.location -- this repo's environmentMatchGlobs only grants jsdom
// to .test.tsx files by default, so a plain .test.ts needs this per-file override.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { configureStore, type Middleware } from '@reduxjs/toolkit'
import connectionReducer, { selectConnected } from '@/shared/store/connectionSlice'
import { wsEventReceived } from '@/shared/store/wsActions'
import { createWsMiddleware, getWsInstance } from '@/shared/store/wsMiddleware'

class FakeWebSocket {
  // Real WebSocket exposes these as static readyState constants; wsMiddleware's connect()
  // guard (`activeWs?.readyState === WebSocket.OPEN`) relies on them existing -- without them
  // `undefined === undefined` would short-circuit the very first connect.
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  static instances: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  readyState = 0
  url: string
  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }
  close() { this.readyState = 3 }
}

function buildTestStore() {
  const middleware = createWsMiddleware()
  const store = configureStore({
    reducer: { connection: connectionReducer },
    middleware: (getDefault) => getDefault().concat(middleware),
  })
  return store
}

describe('wsMiddleware', () => {
  beforeEach(() => {
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.useFakeTimers()
  })
  afterEach(() => {
    // activeWs is a module-level singleton by design (wsMiddleware owns a single app-wide
    // connection); fire onclose on anything still open so it doesn't leak into the next test's
    // connect() guard (which otherwise sees a stale "already connected" activeWs and never
    // creates a fresh instance).
    FakeWebSocket.instances.forEach((ws) => ws.onclose?.())
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('opens a WebSocket and dispatches wsConnected on open', () => {
    const store = buildTestStore()
    store.dispatch({ type: '@@ws/connect' })
    const ws = FakeWebSocket.instances[0]
    ws.onopen?.()
    expect(selectConnected(store.getState() as never)).toBe(true)
    expect(getWsInstance()).toBe(ws as unknown as WebSocket)
  })

  it('dispatches wsEventReceived with the parsed payload on message', () => {
    // wsMiddleware's connect() captures `store.dispatch` by value at store-setup time, before a
    // vi.spyOn(store, 'dispatch') could wrap it -- so a post-hoc spy would silently see zero
    // calls despite the action reaching the reducer. Recording via a plain capture middleware
    // (appended after wsMiddleware, so it observes every action passing through) sidesteps that.
    const seen: unknown[] = []
    const capture: Middleware = () => (next) => (action) => {
      seen.push(action)
      return next(action)
    }
    const middleware = createWsMiddleware()
    const store = configureStore({
      reducer: { connection: connectionReducer },
      middleware: (getDefault) => getDefault().concat(middleware, capture),
    })
    store.dispatch({ type: '@@ws/connect' })
    const ws = FakeWebSocket.instances[0]
    ws.onmessage?.({ data: JSON.stringify({ type: 'archive_build_start', total: 3 }) })
    expect(seen).toContainEqual(wsEventReceived({ type: 'archive_build_start', total: 3 }))
  })

  it('dispatches wsDisconnected and schedules a 3s reconnect on close', () => {
    const store = buildTestStore()
    store.dispatch({ type: '@@ws/connect' })
    const first = FakeWebSocket.instances[0]
    first.onopen?.()
    first.onclose?.()
    expect(selectConnected(store.getState() as never)).toBe(false)
    expect(FakeWebSocket.instances.length).toBe(1)
    vi.advanceTimersByTime(3000)
    expect(FakeWebSocket.instances.length).toBe(2)
  })

  it('connects with since_seq=0 the first time, then reconnects with the highest _seq seen', () => {
    const store = buildTestStore()
    store.dispatch({ type: '@@ws/connect' })
    const first = FakeWebSocket.instances[0]
    expect(first.url).toContain('since_seq=0')
    first.onopen?.()
    first.onmessage?.({ data: JSON.stringify({ type: 'author_loop_done', _seq: 7 }) })
    first.onclose?.()
    vi.advanceTimersByTime(3000)
    const second = FakeWebSocket.instances[1]
    expect(second.url).toContain('since_seq=7')
  })
})
