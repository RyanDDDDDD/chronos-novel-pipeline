import { describe, it, expect } from 'vitest'
import { selectBusy, selectResumable } from '@/shared/store/selectors'

function state(overrides: {
  authorLoopStatus?: string
  resumableChapters?: number[]
} = {}) {
  return {
    authorLoop: {
      status: overrides.authorLoopStatus ?? 'idle', chapter: 0,
      resumableChapters: overrides.resumableChapters ?? [],
    },
  } as never
}

describe('selectBusy', () => {
  it('true when authorLoop is running', () => expect(selectBusy(state({ authorLoopStatus: 'running' }))).toBe(true))
  it('false when idle', () => expect(selectBusy(state())).toBe(false))
})

describe('selectResumable', () => {
  it('reflects membership in resumableChapters', () => {
    expect(selectResumable(3)(state({ resumableChapters: [1, 3] }))).toBe(true)
    expect(selectResumable(2)(state({ resumableChapters: [1, 3] }))).toBe(false)
  })
})
