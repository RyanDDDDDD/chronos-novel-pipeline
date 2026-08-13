import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { Provider } from 'react-redux'
import { configureStore } from '@reduxjs/toolkit'
import portraitGenerationReducer from '@/shared/store/portraitGenerationSlice'
import CastCharacterGridCard from '@/features/setup/components/CastCharacterGridCard'
import type { CastCharacter } from '@/shared/types'

vi.mock('@/shared/queries/novels', () => ({ useActiveNovelId: () => 'novel-A' }))

afterEach(() => cleanup())

function renderCard(character: CastCharacter, preloadedState?: Parameters<typeof configureStore>[0]['preloadedState']) {
  const store = configureStore({
    reducer: { portraitGeneration: portraitGenerationReducer },
    preloadedState,
  })
  render(
    <Provider store={store}>
      <CastCharacterGridCard character={character} onOpen={() => {}} onDelete={async () => ({ ok: true })} />
    </Provider>,
  )
  return store
}

const baseCharacter: CastCharacter = { name: '甲', role: 'protagonist' } as CastCharacter

describe('CastCharacterGridCard', () => {
  it('renders a generating overlay while portrait generation is active', () => {
    renderCard(baseCharacter, {
      portraitGeneration: { byNovelId: { 'novel-A': { 甲: 'generating' } } },
    })
    expect(screen.getByText('生成中…')).not.toBeNull()
  })

  it('renders a failed state with a retry affordance', () => {
    renderCard(baseCharacter, {
      portraitGeneration: { byNovelId: { 'novel-A': { 甲: 'failed' } } },
    })
    expect(screen.getByRole('button', { name: /重新生成/ })).not.toBeNull()
  })

  it('renders plain text layout when there is no portrait and nothing is generating', () => {
    renderCard(baseCharacter)
    expect(screen.queryByText('生成中…')).toBeNull()
    expect(screen.queryByRole('img')).toBeNull()
  })

  it('shows a hover-visible generate button in the idle no-portrait state', () => {
    renderCard(baseCharacter)
    const button = screen.getByRole('button', { name: '生成立绘' })
    expect(button.className).toMatch(/opacity-0/)
  })

  it('shows a hover-visible regenerate button in the idle has-portrait state', () => {
    renderCard({ ...baseCharacter, portrait_path: '甲-123.png' })
    const button = screen.getByRole('button', { name: '重新生成' })
    expect(button.className).toMatch(/opacity-0/)
  })

  it('shows the failed retry button without requiring hover', () => {
    renderCard(baseCharacter, {
      portraitGeneration: { byNovelId: { 'novel-A': { 甲: 'failed' } } },
    })
    const button = screen.getByRole('button', { name: '重新生成' })
    expect(button.className).not.toMatch(/opacity-0/)
  })
})
