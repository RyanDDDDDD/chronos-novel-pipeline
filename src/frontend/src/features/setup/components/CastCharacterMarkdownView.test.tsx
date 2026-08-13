import React from 'react'
import { describe, it, expect } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithClient'
import CastCharacterMarkdownView from '@/features/setup/components/CastCharacterMarkdownView'
import type { CastCharacter } from '@/shared/types'

describe('CastCharacterMarkdownView', () => {
  it('renders slider ladder lines in markdown', async () => {
    const character = {
      name: '角色甲',
      role: 'submissive',
      gender: 'female',
      identity: '身份句',
      sliders: {
        投入: {
          level: 1,
          text: '初见时略带戒备',
          levels: { '0': '戒备', '1': '动摇', '2': '沦陷' },
        },
      },
    } as CastCharacter

    renderWithProviders(
      <CastCharacterMarkdownView character={character} customFieldSpecs={[]} />,
    )

    expect(await screen.findByText(/Lv\.0：戒备/)).toBeTruthy()
    expect(screen.getByText(/Lv\.1：动摇/)).toBeTruthy()
    expect(screen.getByText(/（当前）/)).toBeTruthy()
  })

  it('renders hobbies and background fields', async () => {
    const character = {
      name: '角色甲',
      role: 'submissive',
      gender: 'female',
      race: '人类',
      identity_background: '没落贵族之女，寄人篱下',
      hobbies: ['爱吃甜食', '喜欢刺绣'],
      verbal_tic: '句尾爱加「呢」',
    } as CastCharacter

    renderWithProviders(
      <CastCharacterMarkdownView character={character} customFieldSpecs={[]} />,
    )

    expect(await screen.findByText(/没落贵族之女，寄人篱下/)).toBeTruthy()
    expect(screen.getByText(/爱吃甜食、喜欢刺绣/)).toBeTruthy()
    expect(screen.getByText(/句尾爱加「呢」/)).toBeTruthy()
  })
})
