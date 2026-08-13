import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, cleanup, fireEvent } from '@testing-library/react'
import TokenStatsDashboard from '@/features/stats/components/TokenStatsDashboard'
import { renderWithClient } from '@/test/renderWithClient'

vi.mock('@/features/stats/utils/tokenStatsApi', () => ({
  fetchTokenStats: vi.fn(),
}))
import { fetchTokenStats } from '@/features/stats/utils/tokenStatsApi'

const multiNovelPayload = {
  novels: [
    {
      novel_id: 'default',
      title: '默认',
      subsystems: {
        author_loop: {
          by_chapter: { '6': { tokens_in: 100, tokens_out: 40, tokens_cached: 0 } },
          total: { tokens_in: 100, tokens_out: 40, tokens_cached: 0 },
        },
      },
      total: { tokens_in: 100, tokens_out: 40, tokens_cached: 0 },
    },
    {
      novel_id: 'other',
      title: '另一部小说',
      subsystems: {
        author_loop: {
          by_chapter: { '1': { tokens_in: 50, tokens_out: 20, tokens_cached: 0 } },
          total: { tokens_in: 50, tokens_out: 20, tokens_cached: 0 },
        },
      },
      total: { tokens_in: 50, tokens_out: 20, tokens_cached: 0 },
    },
  ],
  grand_total: { tokens_in: 150, tokens_out: 60, tokens_cached: 0 },
}

beforeEach(() => {
  cleanup()
  vi.mocked(fetchTokenStats).mockClear()
})

afterEach(() => cleanup())

describe('TokenStatsDashboard', () => {
  it('渲染全库合计与小说卡片', async () => {
    vi.mocked(fetchTokenStats).mockResolvedValue({
      novels: [{
        novel_id: 'default',
        title: '默认',
        subsystems: {
          author_loop: {
            by_chapter: {
              '6': { tokens_in: 100, tokens_out: 40, tokens_cached: 0 },
            },
            total: { tokens_in: 100, tokens_out: 40, tokens_cached: 0 },
          },
        },
        total: { tokens_in: 100, tokens_out: 40, tokens_cached: 0 },
      }],
      grand_total: { tokens_in: 100, tokens_out: 40, tokens_cached: 0 },
    })

    renderWithClient(<TokenStatsDashboard />)

    expect(await screen.findByRole('heading', { name: 'Token 统计' })).toBeTruthy()
    expect(screen.getByText('合计')).toBeTruthy()
    expect(screen.getByText('默认')).toBeTruthy()
    expect(screen.getByText('主笔')).toBeTruthy()
    expect(screen.getByText('第 6 章')).toBeTruthy()
  })

  it('无数据时显示空状态', async () => {
    vi.mocked(fetchTokenStats).mockResolvedValue({
      novels: [],
      grand_total: { tokens_in: 0, tokens_out: 0, tokens_cached: 0 },
    })

    renderWithClient(<TokenStatsDashboard />)

    expect(await screen.findByText('暂无小说账本数据')).toBeTruthy()
  })

  it('按小说名称搜索过滤并展开匹配卡片', async () => {
    vi.mocked(fetchTokenStats).mockResolvedValue(multiNovelPayload)

    renderWithClient(<TokenStatsDashboard />)
    await screen.findByText('另一部小说')

    const search = screen.getByRole('searchbox', { name: '搜索小说名称' })
    fireEvent.change(search, { target: { value: '另一' } })

    expect(screen.queryByText('默认')).toBeNull()
    expect(screen.getByText('另一部小说')).toBeTruthy()
    expect(screen.getByText('主笔')).toBeTruthy()
    expect(screen.getByText('第 1 章')).toBeTruthy()
    expect(screen.getByText(/匹配 1/)).toBeTruthy()
  })

  it('搜索无匹配时显示空状态', async () => {
    vi.mocked(fetchTokenStats).mockResolvedValue(multiNovelPayload)

    renderWithClient(<TokenStatsDashboard />)
    await screen.findByText('默认')

    const search = screen.getByRole('searchbox', { name: '搜索小说名称' })
    fireEvent.change(search, { target: { value: '不存在' } })

    expect(screen.getByText('未找到匹配「不存在」的小说')).toBeTruthy()
    expect(screen.queryByText('默认')).toBeNull()
    expect(screen.queryByText('另一部小说')).toBeNull()
  })

  it('defaults to all novels expanded', async () => {
    vi.mocked(fetchTokenStats).mockResolvedValue(multiNovelPayload)

    renderWithClient(<TokenStatsDashboard />)
    await screen.findByText('默认')
    expect(screen.getByText('默认')).toBeTruthy()
    expect(screen.getByText('另一部小说')).toBeTruthy()
    expect(screen.getByText('第 6 章')).toBeTruthy()
    expect(screen.getByText('第 1 章')).toBeTruthy()
  })

  it('re-expands a manually collapsed novel when a search matches it', async () => {
    vi.mocked(fetchTokenStats).mockResolvedValue(multiNovelPayload)

    renderWithClient(<TokenStatsDashboard />)
    await screen.findByText('默认')
    fireEvent.click(screen.getByRole('button', { name: /默认/ }))
    expect(screen.queryByText('第 6 章')).toBeNull()

    const search = screen.getByPlaceholderText('搜索小说名称')
    fireEvent.change(search, { target: { value: '默认' } })
    expect(await screen.findByText('第 6 章')).toBeTruthy()
  })

  it('lets the user manually collapse a currently-matching novel without it snapping back open', async () => {
    vi.mocked(fetchTokenStats).mockResolvedValue(multiNovelPayload)

    renderWithClient(<TokenStatsDashboard />)
    await screen.findByText('默认')

    const search = screen.getByPlaceholderText('搜索小说名称')
    fireEvent.change(search, { target: { value: '默认' } })
    expect(await screen.findByText('第 6 章')).toBeTruthy()

    // Collapse it while the search that matches it is still active -- this must stick
    // (not get force-reopened again on the very next render) as long as the query itself
    // doesn't change.
    fireEvent.click(screen.getByRole('button', { name: /默认/ }))
    expect(screen.queryByText('第 6 章')).toBeNull()
  })
})
