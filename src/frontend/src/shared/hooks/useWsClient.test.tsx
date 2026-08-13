import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { Provider } from 'react-redux'
import { buildTestStore } from '@/test/renderWithClient'
import { wsConnected } from '@/shared/store/connectionSlice'
import { useWsClient } from '@/shared/hooks/useWsClient'

vi.mock('@/shared/store/wsMiddleware', () => ({ getWsInstance: () => 'fake-ws-instance' }))

describe('useWsClient', () => {
  it('returns null while disconnected', () => {
    const store = buildTestStore({ connection: { connected: false } })
    const { result } = renderHook(() => useWsClient(), {
      wrapper: ({ children }) => <Provider store={store}>{children}</Provider>,
    })
    expect(result.current).toBeNull()
  })

  it('returns the ws instance once connected', () => {
    const store = buildTestStore({ connection: { connected: false } })
    const { result, rerender } = renderHook(() => useWsClient(), {
      wrapper: ({ children }) => <Provider store={store}>{children}</Provider>,
    })
    store.dispatch(wsConnected())
    rerender()
    expect(result.current).toBe('fake-ws-instance')
  })
})
