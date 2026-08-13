import { describe, it, expect } from 'vitest'
import { configureStore } from '@reduxjs/toolkit'
import sandboxReducer, { selectSandboxChat } from '@/features/sandbox/store/sandboxSlice'
import { dispatchInboundWsEvent, WsTokenCoalescer } from '@/shared/store/wsInboundDispatch'

describe('WsTokenCoalescer', () => {
  it('apply buffers token frames without synchronous dispatch', () => {
    let calls = 0
    const dispatch = () => { calls += 1 }
    const coalescer = new WsTokenCoalescer()
    expect(coalescer.apply(dispatch, { type: 'story_sandbox_token', delta: 'a' })).toBe(true)
    expect(calls).toBe(0)
  })

  it('coalesces story_sandbox_token deltas within one timer tick', async () => {
    const store = configureStore({ reducer: { sandbox: sandboxReducer } })
    const coalescer = new WsTokenCoalescer()

    dispatchInboundWsEvent(store.dispatch, { type: 'story_sandbox_token', delta: '你' }, coalescer)
    dispatchInboundWsEvent(store.dispatch, { type: 'story_sandbox_token', delta: '好' }, coalescer)

    await new Promise<void>((resolve) => { setTimeout(resolve, 0) })
    expect(selectSandboxChat(store.getState()).liveRound?.prose).toBe('你好')
  })

  it('flushes pending sandbox tokens before a non-token story_sandbox event', () => {
    const store = configureStore({ reducer: { sandbox: sandboxReducer } })
    const coalescer = new WsTokenCoalescer()

    dispatchInboundWsEvent(store.dispatch, { type: 'story_sandbox_token', delta: '片段' }, coalescer)
    dispatchInboundWsEvent(store.dispatch, { type: 'story_sandbox_final', content: '定稿' }, coalescer)
    expect(selectSandboxChat(store.getState()).liveRound?.prose).toBe('定稿')
  })
})
