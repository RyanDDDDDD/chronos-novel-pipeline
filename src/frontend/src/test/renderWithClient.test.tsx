import React from 'react'
import { describe, it, expect } from 'vitest'
import { useQuery } from '@tanstack/react-query'
import { useSelector } from 'react-redux'
import { screen } from '@testing-library/react'
import { renderWithClient, renderWithProviders } from '@/test/renderWithClient'
import type { RootState } from '@/shared/store/store'

function Probe() {
  const { data } = useQuery({ queryKey: ['novels'], queryFn: async () => [] })
  return <div>{data?.[0]?.id ?? 'none'}</div>
}

function ChapterProbe() {
  const chapter = useSelector((s: RootState) => s.ui.chapter)
  return <div>{chapter}</div>
}

describe('renderWithClient', () => {
  it('seed 的 novels 可被 useQuery 读到', async () => {
    renderWithClient(<Probe />, { activeNovelId: 'abc' })
    expect(await screen.findByText('abc')).toBeTruthy()
  })
})

describe('renderWithProviders', () => {
  it('preloadedState 可被 useSelector 读到', () => {
    renderWithProviders(<ChapterProbe />, { preloadedState: { ui: { chapter: 42, setupTab: 'world' } } })
    expect(screen.getByText('42')).toBeTruthy()
  })
})
