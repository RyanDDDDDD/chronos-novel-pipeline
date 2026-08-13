import { describe, it, expect } from 'vitest'
import servicePingReducer, {
  pingStarted, pingSucceeded, pingFailed, pingDisabled, serviceStatusLoaded,
} from '@/shared/store/servicePingSlice'

const initial = {
  llm: { status: 'unknown', error: null },
  search: { status: 'unknown', error: null },
}

describe('servicePingSlice', () => {
  it('starts unknown for both targets', () => {
    expect(servicePingReducer(undefined, { type: '@@INIT' })).toEqual(initial)
  })

  it('pingStarted sets checking for the target only', () => {
    const state = servicePingReducer(initial, pingStarted('llm'))
    expect(state.llm).toEqual({ status: 'checking', error: null })
    expect(state.search).toEqual({ status: 'unknown', error: null })
  })

  it('pingSucceeded sets ok', () => {
    const state = servicePingReducer(initial, pingSucceeded('search'))
    expect(state.search).toEqual({ status: 'ok', error: null })
  })

  it('pingFailed sets error with message', () => {
    const state = servicePingReducer(initial, pingFailed({ target: 'llm', error: '401' }))
    expect(state.llm).toEqual({ status: 'error', error: '401' })
  })

  it('pingDisabled sets disabled', () => {
    const state = servicePingReducer(initial, pingDisabled('search'))
    expect(state.search).toEqual({ status: 'disabled', error: null })
  })

  it('serviceStatusLoaded replaces both entries', () => {
    const payload = {
      llm: { status: 'ok' as const, error: null },
      search: { status: 'error' as const, error: 'bad key' },
    }
    const state = servicePingReducer(initial, serviceStatusLoaded(payload))
    expect(state).toEqual(payload)
  })
})
