import { describe, expect, it } from 'vitest'
import {
  clearDerivationPending,
  markDerivationsPending,
} from '@/features/sandbox/utils/sandboxDeriveFields'

describe('sandboxDeriveFields', () => {
  it('marks only known derive fields pending', () => {
    expect(markDerivationsPending({}, ['characterStates', 'suggestions', 'unknown'])).toEqual({
      characterStates: true,
      suggestions: true,
    })
  })

  it('clears a single pending field', () => {
    const prev = { characterStates: true, suggestions: true }
    expect(clearDerivationPending(prev, 'characterStates')).toEqual({ suggestions: true })
    expect(clearDerivationPending(prev, 'suggestions')).toEqual({ characterStates: true })
  })

  it('marks sceneState/initialSceneState pending too', () => {
    expect(markDerivationsPending({}, ['sceneState', 'initialSceneState'])).toEqual({
      sceneState: true, initialSceneState: true,
    })
  })
})
