import { describe, it, expect, vi, afterEach } from 'vitest'
import { fetchServiceStatus } from '@/shared/api/servicePing'
import { serviceStatusLoaded } from '@/shared/store/servicePingSlice'
import type { AppDispatch } from '@/shared/store/store'

afterEach(() => {
  vi.unstubAllGlobals()
})

function fakeDispatch(): { dispatch: AppDispatch; calls: unknown[] } {
  const calls: unknown[] = []
  const dispatch = ((action: unknown) => { calls.push(action); return action }) as AppDispatch
  return { dispatch, calls }
}

describe('servicePing api', () => {
  it('fetchServiceStatus dispatches serviceStatusLoaded on ok response', async () => {
    const payload = {
      llm: { status: 'ok' as const, error: null },
      search: { status: 'disabled' as const, error: null },
    }
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => payload })))
    const { dispatch, calls } = fakeDispatch()
    await fetchServiceStatus(dispatch)
    expect(calls).toEqual([serviceStatusLoaded(payload)])
  })

  it('fetchServiceStatus does not dispatch on network failure', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network down') }))
    const { dispatch, calls } = fakeDispatch()
    await fetchServiceStatus(dispatch)
    expect(calls).toEqual([])
  })

  it('fetchServiceStatus does not dispatch on malformed body', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ llm: null }) })))
    const { dispatch, calls } = fakeDispatch()
    await fetchServiceStatus(dispatch)
    expect(calls).toEqual([])
  })
})
