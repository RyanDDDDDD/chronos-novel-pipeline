import React from 'react'
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import PlotChapterSummaryCard from '@/features/setup/components/PlotChapterSummaryCard'

beforeEach(() => {
  cleanup()
})

describe('PlotChapterSummaryCard', () => {
  it('renders core_xp, char counts, and recognized characters together', () => {
    render(
      <PlotChapterSummaryCard
        coreXp={['天真猎物', '首次开苞']}
        charCounts={{
          stages: [{ stage_num: 1, outline: 7, beats: 4 }],
          outlineTotal: 7,
          beatsTotal: 4,
        }}
        recognizedCharacters={['甲', '乙']}
        hasOutlineText
      />,
    )
    expect(screen.getByText('题材基调')).toBeTruthy()
    expect(screen.getByText('天真猎物')).toBeTruthy()
    expect(screen.getByText('本章字数')).toBeTruthy()
    expect(screen.getByText(/粗大纲 7 字/)).toBeTruthy()
    expect(screen.getByText(/分拍底稿 4 字/)).toBeTruthy()
    expect(screen.getByText('本章角色')).toBeTruthy()
    expect(screen.getByText('甲、乙')).toBeTruthy()
  })

  it('shows 无 when outline text has no recognized characters', () => {
    render(
      <PlotChapterSummaryCard
        coreXp={[]}
        charCounts={null}
        recognizedCharacters={[]}
        hasOutlineText
      />,
    )
    expect(screen.getByText('本章角色')).toBeTruthy()
    expect(screen.getByText('无')).toBeTruthy()
  })

  it('renders nothing when all sections are empty', () => {
    const { container } = render(
      <PlotChapterSummaryCard
        coreXp={[]}
        charCounts={null}
        recognizedCharacters={[]}
        hasOutlineText={false}
      />,
    )
    expect(container.firstChild).toBeNull()
  })
})
