import { describe, it, expect } from 'vitest'
import type { Round } from '@/features/sandbox/hooks/useStorySandbox'
import {
  inferSubmittedDirections,
  parseInstructionListItems,
} from '@/features/sandbox/utils/reconstructSubmittedDirections'

const baseRound = (over: Partial<Round>): Round => ({
  instruction: '继续',
  prose: '正文',
  characterStates: {},
  suggestions: [],
  sceneState: {},
  ...over,
})

describe('parseInstructionListItems', () => {
  it('extracts markdown list lines', () => {
    expect(parseInstructionListItems('- 甲追出去\n\n再加一点')).toEqual(['甲追出去'])
  })

  it('returns empty for plain text without list markers', () => {
    expect(parseInstructionListItems('继续')).toEqual([])
  })
})

describe('inferSubmittedDirections', () => {
  it('fills submittedDirections from the next round instruction when missing', () => {
    const rounds = [
      baseRound({ suggestions: ['甲追出去', '乙沉默'] }),
      baseRound({ instruction: '- 甲追出去\n\n再加一点' }),
    ]
    const out = inferSubmittedDirections(rounds)
    expect(out[0].submittedDirections).toEqual(['甲追出去'])
  })

  it('leaves rounds unchanged when submittedDirections already present', () => {
    const rounds = [
      baseRound({ suggestions: ['甲'], submittedDirections: ['甲'] }),
      baseRound({ instruction: '- 乙' }),
    ]
    expect(inferSubmittedDirections(rounds)[0].submittedDirections).toEqual(['甲'])
  })

  it('ignores list items not in the prior suggestions', () => {
    const rounds = [
      baseRound({ suggestions: ['甲'] }),
      baseRound({ instruction: '- 手打内容' }),
    ]
    expect(inferSubmittedDirections(rounds)[0].submittedDirections).toBeUndefined()
  })
})
