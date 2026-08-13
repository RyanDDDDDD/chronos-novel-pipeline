import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import ReviewSkillDropNode from '@/features/pipeline/components/ReviewSkillDropNode'
import { renderWithClient } from '@/test/renderWithClient'

vi.mock('@xyflow/react', () => ({
  Handle: () => null,
  Position: { Left: 'left', Right: 'right' },
}))

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

function renderNode() {
  return renderWithClient(
    <ReviewSkillDropNode data={{ label: '文风/过渡审查', novelId: 'default', group: 'buildtime' }} />,
  )
}

describe('ReviewSkillDropNode', () => {
  it('展示已启用 skill 列表，未启用的不显示', async () => {
    renderNode()
    expect(await screen.findByText('衔接判官')).toBeTruthy()
    expect(screen.queryByText('文风判官')).toBeNull()
  })

  it('点 ✕ 把该 skill 加入 disabled 数组', async () => {
    renderNode()
    const removeBtn = await screen.findByRole('button', { name: /删除衔接判官/ })
    fireEvent.click(removeBtn)
    await waitFor(() => {
      expect(putDialogueConfig.mock.calls.at(-1)?.[1]).toEqual({
        dialogue: { disabled_buildtime_review_hooks: ['style', 'coherence'] },
      })
    })
  })

  it('drop 命中同 group 的 payload 时启用该 skill', async () => {
    renderNode()
    await screen.findByText('衔接判官')
    const node = screen.getByText('文风/过渡审查')
    const dropTarget = node.closest('[data-testid="review-skill-drop-node"]') as HTMLElement
    const dataTransfer = { getData: () => JSON.stringify({ name: 'style', group: 'buildtime' }) }
    fireEvent.drop(dropTarget, { dataTransfer })
    await waitFor(() => {
      expect(putDialogueConfig.mock.calls.at(-1)?.[1]).toEqual({
        dialogue: { disabled_buildtime_review_hooks: [] },
      })
    })
  })

  it('drop 命中不同 group 的 payload 时静默不做任何操作', async () => {
    renderNode()
    const node = await screen.findByText('文风/过渡审查')
    const dropTarget = node.closest('[data-testid="review-skill-drop-node"]') as HTMLElement
    const dataTransfer = { getData: () => JSON.stringify({ name: 'fidelity', group: 'runtime' }) }
    fireEvent.drop(dropTarget, { dataTransfer })
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(putDialogueConfig).not.toHaveBeenCalled()
  })
})
