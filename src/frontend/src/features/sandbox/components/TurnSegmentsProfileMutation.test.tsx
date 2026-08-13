import React from 'react'
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { TurnSegments } from './StorySandboxSegments'
import type { Round } from '@/features/sandbox/hooks/useStorySandbox'

afterEach(() => {
  cleanup()
})

const BASE_ROUND: Round = {
  instruction: '继续', prose: '正文', characterStates: {}, suggestions: [],
  sceneState: {},
}

describe('TurnSegments profile-mutation rendering', () => {
  it('renders ProfileMutationBubble when the round has a mutation', () => {
    render(
      <TurnSegments
        round={{ ...BASE_ROUND, profileMutation: { 甲: { race: '精灵' } } }}
        hiddenCats={new Set()} selectedDirections={new Set()}
        onToggleDirection={() => {}} isLatest={false}
      />,
    )
    expect(screen.getByText(/🧬 档案\/关系突变/)).toBeTruthy()
  })

  it('renders nothing extra when the round has no mutation', () => {
    render(
      <TurnSegments
        round={{ ...BASE_ROUND, profileMutation: null }}
        hiddenCats={new Set()} selectedDirections={new Set()}
        onToggleDirection={() => {}} isLatest={false}
      />,
    )
    expect(screen.queryByText(/🧬 档案\/关系突变/)).toBeNull()
  })

  it('hides the bubble when the state category is hidden', () => {
    render(
      <TurnSegments
        round={{ ...BASE_ROUND, profileMutation: { 甲: { race: '精灵' } } }}
        hiddenCats={new Set(['state'])} selectedDirections={new Set()}
        onToggleDirection={() => {}} isLatest={false}
      />,
    )
    expect(screen.queryByText(/🧬 档案\/关系突变/)).toBeNull()
  })
})
