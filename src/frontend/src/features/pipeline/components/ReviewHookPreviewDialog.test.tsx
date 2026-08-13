import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, cleanup } from '@testing-library/react'
import ReviewHookPreviewDialog from '@/features/pipeline/components/ReviewHookPreviewDialog'
import { renderWithClient } from '@/test/renderWithClient'

vi.mock('@/features/pipeline/utils/reviewHookCard', () => ({
  fetchReviewHookCard: vi.fn(),
}))
import { fetchReviewHookCard } from '@/features/pipeline/utils/reviewHookCard'

beforeEach(() => {
  cleanup()
  vi.mocked(fetchReviewHookCard).mockReset()
})
afterEach(() => cleanup())

describe('ReviewHookPreviewDialog', () => {
  it('有 content 时渲染 markdown', async () => {
    vi.mocked(fetchReviewHookCard).mockResolvedValue({ name: 'style', content: '# 文风判官\n检查用词' })
    renderWithClient(<ReviewHookPreviewDialog name="style" title="文风判官" onClose={() => {}} />)
    expect(await screen.findByText('文风判官', { selector: 'h1' })).toBeTruthy()
  })

  it('content 为 null 时显示无规则卡片提示', async () => {
    vi.mocked(fetchReviewHookCard).mockResolvedValue({ name: 'expansion_ratio', content: null })
    renderWithClient(<ReviewHookPreviewDialog name="expansion_ratio" title="扩写倍率" onClose={() => {}} />)
    expect(await screen.findByText('该判官为纯代码判定，无规则卡片明文')).toBeTruthy()
  })
})
