import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { renderWithClient } from '@/test/renderWithClient'
import AuthorCharacterPanel from '@/features/author/components/AuthorCharacterPanel'

vi.mock('@/shared/utils/archives', () => ({
  fetchArchiveOverview: vi.fn(),
  fetchChapterArchives: vi.fn(),
}))
vi.mock('@/shared/utils/setup', () => ({
  fetchCast: vi.fn(),
  fetchRelationshipGraph: vi.fn(),
}))
import { fetchChapterArchives } from '@/shared/utils/archives'
import { fetchCast, fetchRelationshipGraph } from '@/shared/utils/setup'

beforeEach(() => {
  cleanup()
  try {
    localStorage.setItem('chronos.authorCharacterPanel.collapsed', '0')
  } catch {
    /* test env may lack localStorage */
  }
  vi.mocked(fetchChapterArchives).mockResolvedValue({
    chapter: 2,
    characters: [{
      name: '角色A',
      role: '测试',
      causal_anchors: {},
      sliders: { resistance: { value: 4, label: '抗拒中' } },
      location: 'X',
      gender: 'female',
    }],
  })
  vi.mocked(fetchCast).mockResolvedValue([])
  vi.mocked(fetchRelationshipGraph).mockResolvedValue({ groups: {}, edges: {} })
})

describe('AuthorCharacterPanel', () => {
  it('展示章节标题与角色卡，支持折叠/展开', async () => {
    renderWithClient(<AuthorCharacterPanel chapter={2} />)
    expect(await screen.findByText('本章角色档案')).toBeTruthy()
    expect(screen.getByText('第2章')).toBeTruthy()
    expect(await screen.findByText('角色A')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '全部展开' }))
    expect(await screen.findByText('抗拒中')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '全部折叠' }))
    await waitFor(() => {
      expect(screen.queryByText('抗拒中')).toBeNull()
    })
  })

  it('无档案时显示空态', async () => {
    vi.mocked(fetchChapterArchives).mockResolvedValue({ chapter: 3, characters: [] })
    renderWithClient(<AuthorCharacterPanel chapter={3} />)
    expect(await screen.findByText(/第3章暂无角色档案/)).toBeTruthy()
  })

  it('可手动收起/展开整个 panel', async () => {
    renderWithClient(<AuthorCharacterPanel chapter={2} />)
    expect(await screen.findByText('本章角色档案')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '收起角色档案' }))
    expect(screen.queryByText('本章角色档案')).toBeNull()
    expect(screen.getByRole('button', { name: '展开角色档案' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '展开角色档案' }))
    expect(await screen.findByText('本章角色档案')).toBeTruthy()
  })

  it('passes hasPortrait=true to CharacterCard when the cast roster has a portrait_path', async () => {
    vi.mocked(fetchCast).mockResolvedValue([{ name: '角色A', portrait_path: '角色A-123.png' }])
    const { container } = renderWithClient(<AuthorCharacterPanel chapter={2} />)
    await screen.findByText('角色A')
    expect(container.querySelector('img')).not.toBeNull()
  })
})
