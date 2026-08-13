import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import AuthorLoopConfigPanel from '@/features/pipeline/components/AuthorLoopConfigPanel'
import { renderWithClient } from '@/test/renderWithClient'
import { SidebarProvider } from '@/shared/components/ui/sidebar'

vi.mock('@/features/pipeline/utils/authorLoopDialogueConfig', () => ({
  fetchDialogueConfig: vi.fn(),
  putDialogueConfig: vi.fn(),
}))
import { fetchDialogueConfig, putDialogueConfig } from '@/features/pipeline/utils/authorLoopDialogueConfig'

function baseConfig(overrides: Record<string, unknown> = {}) {
  return {
    config: {
      target_words: 3000,
      disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
      auto_build_character_count: 5, auto_build_chapter_count: 3,
      chat_identity: '', recall_cooldown_turns: 10, recall_top_k: 5,
      ...overrides,
    },
    default_identity: '',
    buildtime_review_hooks: [],
    runtime_review_hooks: [],
    setup_review_hooks: [],
  }
}

beforeEach(() => {
  cleanup()
  vi.mocked(fetchDialogueConfig).mockClear().mockResolvedValue(baseConfig())
  vi.mocked(putDialogueConfig).mockClear().mockResolvedValue(baseConfig())
})
afterEach(() => cleanup())

function renderPanel() {
  renderWithClient(
    <SidebarProvider>
      <AuthorLoopConfigPanel novelId="default" onSelectNode={vi.fn()} />
    </SidebarProvider>,
  )
}

describe('AuthorLoopConfigPanel', () => {
  it('渲染冷却窗口与 Top-K 输入框，回显默认值', async () => {
    renderPanel()
    const cooldown = await screen.findByLabelText('冷却窗口') as HTMLInputElement
    const topK = await screen.findByLabelText('Top-K') as HTMLInputElement
    expect(cooldown.value).toBe('10')
    expect(topK.value).toBe('5')
  })

  it('修改冷却窗口失焦后保存', async () => {
    renderPanel()
    const input = await screen.findByLabelText('冷却窗口') as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '20' } })
    fireEvent.blur(input)
    await waitFor(() => {
      expect(putDialogueConfig.mock.calls.at(-1)?.[1]).toEqual({ dialogue: { recall_cooldown_turns: 20 } })
    })
  })

  it('冷却窗口超过 50 会被 clamp 到 50', async () => {
    renderPanel()
    const input = await screen.findByLabelText('冷却窗口') as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '999' } })
    fireEvent.blur(input)
    await waitFor(() => {
      expect(putDialogueConfig.mock.calls.at(-1)?.[1]).toEqual({ dialogue: { recall_cooldown_turns: 50 } })
    })
    expect(input.value).toBe('50')
  })

  it('修改 Top-K 失焦后保存', async () => {
    renderPanel()
    const input = await screen.findByLabelText('Top-K') as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '8' } })
    fireEvent.blur(input)
    await waitFor(() => {
      expect(putDialogueConfig.mock.calls.at(-1)?.[1]).toEqual({ dialogue: { recall_top_k: 8 } })
    })
  })

  it('Top-K 超过 20 会被 clamp 到 20', async () => {
    renderPanel()
    const input = await screen.findByLabelText('Top-K') as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '99' } })
    fireEvent.blur(input)
    await waitFor(() => {
      expect(putDialogueConfig.mock.calls.at(-1)?.[1]).toEqual({ dialogue: { recall_top_k: 20 } })
    })
    expect(input.value).toBe('20')
  })

  it('Top-K 低于 1 会被 clamp 到 1', async () => {
    renderPanel()
    const input = await screen.findByLabelText('Top-K') as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '0' } })
    fireEvent.blur(input)
    await waitFor(() => {
      expect(putDialogueConfig.mock.calls.at(-1)?.[1]).toEqual({ dialogue: { recall_top_k: 1 } })
    })
  })
})
