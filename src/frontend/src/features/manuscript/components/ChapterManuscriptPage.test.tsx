import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import ChapterManuscriptPage from '@/features/manuscript/components/ChapterManuscriptPage'
import { renderWithProviders } from '@/test/renderWithClient'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.includes('/api/chapters/manuscripts')) {
      return { ok: true, json: async () => ({ chapters: [{ chapter: 2, path: '/x/第2章_主笔.md' }] }) }
    }
    if (url.includes('/api/chapters/2/manuscript')) {
      return {
        ok: true,
        json: async () => ({
          ok: true,
          chapter: 2,
          path: '/x/第2章_主笔.md',
          content: '### 【阶段一：起】\n\n- **【过程描述】**：正文',
        }),
      }
    }
    if (url.includes('/api/chapters/1/manuscript')) {
      return { ok: false, status: 404, json: async () => ({ ok: false, error: '暂无' }) }
    }
    if (url.includes('/api/chapters')) {
      return { ok: true, json: async () => ({ chapters: [{ chapter: 2, title: '试章' }] }) }
    }
    return { ok: true, json: async () => ({}) }
  }) as unknown as typeof fetch)
})

function renderPage(chapter = 2) {
  return renderWithProviders(<ChapterManuscriptPage />, {
    activeNovelId: 'n1',
    preloadedState: { ui: { chapter, setupTab: 'world' } },
  })
}

describe('ChapterManuscriptPage', () => {
  it('渲染已保存章节的成稿正文与字数', async () => {
    renderPage(2)
    expect(await screen.findByText(/【阶段一：起】/)).toBeTruthy()
    expect(screen.getByText(/24 字/)).toBeTruthy()
    expect(screen.queryByText(/第2章_主笔\.md/)).toBeNull()
  })

  it('无成稿时显示空态', async () => {
    renderPage(1)
    expect(await screen.findByText(/尚无保存的主笔成稿/)).toBeTruthy()
  })
})
