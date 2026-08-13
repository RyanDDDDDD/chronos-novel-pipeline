import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, cleanup } from '@testing-library/react'
import ReviewHookGroupSection from '@/features/pipeline/components/ReviewHookGroupSection'
import { renderWithClient } from '@/test/renderWithClient'

vi.mock('@/features/pipeline/utils/authorLoopDialogueConfig', () => ({
  fetchDialogueConfig: vi.fn(),
  putDialogueConfig: vi.fn(),
}))
import { fetchDialogueConfig, putDialogueConfig } from '@/features/pipeline/utils/authorLoopDialogueConfig'

function baseConfig() {
  return {
    config: {
      target_words: 3000,
      disabled_buildtime_review_hooks: ['style'], disabled_runtime_review_hooks: [],
      disabled_setup_review_hooks: [],
    },
    buildtime_review_hooks: [
      { name: 'coherence', display_name: '衔接判官', axis: 'transition', enabled: true },
      { name: 'style', display_name: '文风判官', axis: 'stage', enabled: false },
    ],
    runtime_review_hooks: [],
    setup_review_hooks: [],
  }
}

beforeEach(() => {
  cleanup()
  vi.mocked(fetchDialogueConfig).mockReset().mockResolvedValue(baseConfig())
  vi.mocked(putDialogueConfig).mockReset().mockResolvedValue(baseConfig())
})
afterEach(() => cleanup())

function renderSection(onSelectNode = vi.fn()) {
  return renderWithClient(
    <ReviewHookGroupSection novelId="default" group="buildtime" llmParamNodeId="review" onSelectNode={onSelectNode} />,
  )
}

describe('ReviewHookGroupSection', () => {
  it('渲染全量 skill 卡片（含已禁用），无 checkbox', async () => {
    renderSection()
    expect(await screen.findByText('衔接判官')).toBeTruthy()
    expect(screen.getByText('文风判官')).toBeTruthy()
    expect(screen.queryByRole('checkbox')).toBeNull()
  })

  it('已启用的卡片带"已启用"标记，未启用的没有', async () => {
    renderSection()
    const enabledCard = (await screen.findByText('衔接判官')).closest('[draggable]') as HTMLElement
    const disabledCard = screen.getByText('文风判官').closest('[draggable]') as HTMLElement
    expect(enabledCard.textContent).toContain('已启用')
    expect(disabledCard.textContent).not.toContain('已启用')
  })

  it('卡片可拖拽，dragstart 写入 name+group 到 dataTransfer', async () => {
    renderSection()
    const card = (await screen.findByText('文风判官')).closest('[draggable]') as HTMLElement
    expect(card.getAttribute('draggable')).toBe('true')
    const setData = vi.fn()
    fireEvent.dragStart(card, { dataTransfer: { setData } })
    expect(setData).toHaveBeenCalledWith('application/json', JSON.stringify({ name: 'style', group: 'buildtime' }))
  })

  it('点预览按钮打开 ReviewHookPreviewDialog', async () => {
    renderSection()
    const previewButtons = await screen.findAllByRole('button', { name: /预览/ })
    fireEvent.click(previewButtons[0])
    expect(await screen.findByText('规则卡片预览')).toBeTruthy()
  })

  it('点采样参数按钮调用 onSelectNode(llmParamNodeId)', async () => {
    const onSelectNode = vi.fn()
    renderSection(onSelectNode)
    const btn = await screen.findByRole('button', { name: '采样参数' })
    fireEvent.click(btn)
    expect(onSelectNode).toHaveBeenCalledWith('review')
  })
})
