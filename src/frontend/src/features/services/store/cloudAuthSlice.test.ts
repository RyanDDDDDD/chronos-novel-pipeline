import { describe, it, expect } from 'vitest'
import cloudAuthReducer from '@/features/services/store/cloudAuthSlice'
import { wsEventReceived } from '@/shared/store/wsActions'

describe('cloudAuthSlice reducer', () => {
  it('starts logged out', () => {
    expect(cloudAuthReducer(undefined, { type: '@@INIT' })).toEqual({ isLoggedIn: false, lastErrorCode: null })
  })

  it('cloud_auth_login_succeeded sets isLoggedIn true and clears lastErrorCode', () => {
    const prev = { isLoggedIn: false, lastErrorCode: 'INVALID_CREDENTIALS' }
    const state = cloudAuthReducer(prev, wsEventReceived({ type: 'cloud_auth_login_succeeded' }))
    expect(state).toEqual({ isLoggedIn: true, lastErrorCode: null })
  })

  it('cloud_auth_login_failed sets lastErrorCode and keeps isLoggedIn false', () => {
    const state = cloudAuthReducer(
      { isLoggedIn: false, lastErrorCode: null },
      wsEventReceived({ type: 'cloud_auth_login_failed', error_code: 'INVALID_CREDENTIALS' }),
    )
    expect(state).toEqual({ isLoggedIn: false, lastErrorCode: 'INVALID_CREDENTIALS' })
  })

  it('cloud_auth_logged_out sets isLoggedIn false', () => {
    const state = cloudAuthReducer(
      { isLoggedIn: true, lastErrorCode: null },
      wsEventReceived({ type: 'cloud_auth_logged_out' }),
    )
    expect(state.isLoggedIn).toBe(false)
  })
})
