import { describe, it, expect } from 'vitest'
import connectionReducer, { wsConnected, wsDisconnected, selectConnected } from '@/shared/store/connectionSlice'

describe('connectionSlice', () => {
  it('starts disconnected', () => {
    expect(connectionReducer(undefined, { type: '@@INIT' })).toEqual({ connected: false })
  })

  it('wsConnected sets connected true', () => {
    const state = connectionReducer({ connected: false }, wsConnected())
    expect(state.connected).toBe(true)
  })

  it('wsDisconnected sets connected false', () => {
    const state = connectionReducer({ connected: true }, wsDisconnected())
    expect(state.connected).toBe(false)
  })

  it('selectConnected reads the connected flag', () => {
    expect(selectConnected({ connection: { connected: true } } as never)).toBe(true)
  })
})
