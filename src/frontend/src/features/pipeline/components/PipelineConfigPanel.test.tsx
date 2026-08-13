// src/frontend/src/components/__tests__/PipelineConfigPanel.test.tsx
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import PipelineConfigPanel from '@/features/pipeline/components/PipelineConfigPanel'
import { renderWithClient } from '@/test/renderWithClient'
import { SidebarProvider } from '@/shared/components/ui/sidebar'

vi.mock('@/features/pipeline/utils/authorLoopDialogueConfig', () => ({
  fetchDialogueConfig: vi.fn(),
  putDialogueConfig: vi.fn(),
}))
vi.mock('@/shared/utils/chronosConfig', () => ({
  fetchChronosConfig: vi.fn(),
  saveChronosConfig: vi.fn(),
  resolveNovelImport: vi.fn((cfg) => ({
    chunk_size: cfg?.novel_import?.chunk_size ?? 10000,
    concurrency: cfg?.novel_import?.concurrency ?? null,
    warn_threshold_chars: cfg?.novel_import?.warn_threshold_chars ?? 100000,
    compaction_interval: cfg?.novel_import?.compaction_interval ?? 5,
  })),
  clampInt: vi.fn((v: string, fallback: number) => {
    const n = Number.parseInt(v, 10)
    return Number.isFinite(n) ? n : fallback
  }),
  NOVEL_IMPORT_DEFAULTS: {
    chunk_size: 10000,
    concurrency: null,
    warn_threshold_chars: 100000,
    compaction_interval: 5,
  },
}))
import { fetchDialogueConfig, putDialogueConfig } from '@/features/pipeline/utils/authorLoopDialogueConfig'
import { fetchChronosConfig, saveChronosConfig } from '@/shared/utils/chronosConfig'

beforeEach(() => {
  cleanup()
  vi.mocked(fetchDialogueConfig).mockClear()
  vi.mocked(putDialogueConfig).mockClear()
  vi.mocked(fetchChronosConfig).mockClear()
  vi.mocked(saveChronosConfig).mockClear()
  vi.mocked(fetchChronosConfig).mockResolvedValue({
    novel_import: {
      chunk_size: 10000, concurrency: null,
      warn_threshold_chars: 100000, compaction_interval: 5,
    },
  })
  vi.mocked(saveChronosConfig).mockImplementation(async cfg => cfg)
  vi.mocked(fetchDialogueConfig).mockResolvedValue({
    config: {
      target_words: 3000,
      disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
      auto_build_character_count: 5, auto_build_chapter_count: 3,
      chat_identity: '',
    },
    default_identity: '',
    buildtime_review_hooks: [],
    runtime_review_hooks: [],
    setup_review_hooks: [],
  })
  vi.mocked(putDialogueConfig).mockResolvedValue({
    config: {
      target_words: 3500,
      disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
      auto_build_character_count: 5, auto_build_chapter_count: 3,
      chat_identity: '',
    },
    default_identity: '',
    buildtime_review_hooks: [],
    runtime_review_hooks: [],
    setup_review_hooks: [],
  })
})
afterEach(() => cleanup())

function renderPanel() {
  renderWithClient(
    <SidebarProvider>
      <PipelineConfigPanel novelId="default" onSelectNode={vi.fn()} />
    </SidebarProvider>,
  )
}

describe('PipelineConfigPanel', () => {
  it('渲染对话agent人物设定文本框（默认空）', async () => {
    renderPanel()
    const textarea = await screen.findByLabelText('对话agent 人物设定') as HTMLTextAreaElement
    expect(textarea.value).toBe('')
  })

  it('失焦时保存 trim 后的人物设定文本', async () => {
    renderPanel()
    const textarea = await screen.findByLabelText('对话agent 人物设定')
    fireEvent.change(textarea, { target: { value: '  自定义身份  ' } })
    fireEvent.blur(textarea)
    await waitFor(() => {
      expect(putDialogueConfig.mock.calls.at(-1)?.[1]).toEqual({ dialogue: { chat_identity: '自定义身份' } })
    })
  })

  it('人物设定恢复默认按钮清空并立即保存，为空时禁用', async () => {
    renderPanel()
    const resetButton = await screen.findByRole('button', { name: '恢复默认' }) as HTMLButtonElement
    expect(resetButton.disabled).toBe(true)

    const textarea = screen.getByLabelText('对话agent 人物设定')
    fireEvent.change(textarea, { target: { value: '自定义身份' } })
    fireEvent.blur(textarea)
    await waitFor(() => expect(resetButton.disabled).toBe(false))

    fireEvent.click(resetButton)
    await waitFor(() => {
      expect(putDialogueConfig.mock.calls.at(-1)?.[1]).toEqual({ dialogue: { chat_identity: '' } })
    })
  })

  it('渲染字数滑块（文风/内容分级已迁至 header，细节强调技能已迁出侧栏）', async () => {
    renderPanel()
    expect(await screen.findByRole('heading', { name: '流水线配置' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: '文风' })).toBeNull()
    expect(screen.queryByRole('heading', { name: '细节强调技能' })).toBeNull()
    expect(screen.getByLabelText('章节字数目标')).toBeTruthy()
    expect(screen.getByLabelText('章节字数滑块')).toBeTruthy()
  })

  it('拖动字数滑块触发保存', async () => {
    renderPanel()
    const slider = await screen.findByLabelText('章节字数滑块') as HTMLInputElement
    const input = screen.getByLabelText('章节字数目标') as HTMLInputElement
    fireEvent.change(slider, { target: { value: '4200' } })
    fireEvent.pointerUp(slider)
    await waitFor(() => {
      expect(putDialogueConfig.mock.calls.at(-1)?.[1]).toEqual({ dialogue: { target_words: 4200 } })
    })
    expect(input.value).toBe('4,200')
  })

  it('手动输入字数失焦后触发保存', async () => {
    renderPanel()
    const input = await screen.findByLabelText('章节字数目标') as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '12000' } })
    fireEvent.blur(input)
    await waitFor(() => {
      expect(putDialogueConfig.mock.calls.at(-1)?.[1]).toEqual({ dialogue: { target_words: 12000 } })
    })
    expect((screen.getByLabelText('章节字数滑块') as HTMLInputElement).value).toBe('12000')
  })

  it('渲染角色数量与章节数量输入框', async () => {
    renderPanel()
    expect(await screen.findByLabelText('角色数量')).toBeTruthy()
    expect(screen.getByLabelText('章节数量')).toBeTruthy()
  })

  it('手动输入角色数量失焦后触发保存', async () => {
    renderPanel()
    const input = await screen.findByLabelText('角色数量') as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '8' } })
    fireEvent.blur(input)
    await waitFor(() => {
      expect(putDialogueConfig.mock.calls.at(-1)?.[1]).toEqual({ dialogue: { auto_build_character_count: 8 } })
    })
  })

  it('手动输入章节数量失焦后触发保存', async () => {
    renderPanel()
    const input = await screen.findByLabelText('章节数量') as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '12' } })
    fireEvent.blur(input)
    await waitFor(() => {
      expect(putDialogueConfig.mock.calls.at(-1)?.[1]).toEqual({ dialogue: { auto_build_chapter_count: 12 } })
    })
  })

  it('chat_identity 为空时输入框显示 default_identity（内容包/系统默认解析结果）', async () => {
    vi.mocked(fetchDialogueConfig).mockResolvedValue({
      config: {
        target_words: 3000,
        disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
        auto_build_character_count: 5, auto_build_chapter_count: 3,
        chat_identity: '',
      },
      default_identity: '内容包默认身份',
      buildtime_review_hooks: [],
      runtime_review_hooks: [],
    })
    renderPanel()
    const textarea = await screen.findByLabelText('对话agent 人物设定') as HTMLTextAreaElement
    await waitFor(() => {
      expect(textarea.value).toBe('内容包默认身份')
    })
  })

  it('显示 default_identity 时恢复默认按钮保持禁用（未产生真实覆写）', async () => {
    vi.mocked(fetchDialogueConfig).mockResolvedValue({
      config: {
        target_words: 3000,
        disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
        auto_build_character_count: 5, auto_build_chapter_count: 3,
        chat_identity: '',
      },
      default_identity: '内容包默认身份',
      buildtime_review_hooks: [],
      runtime_review_hooks: [],
    })
    renderPanel()
    await screen.findByLabelText('对话agent 人物设定')
    const resetButton = screen.getByRole('button', { name: '恢复默认' }) as HTMLButtonElement
    expect(resetButton.disabled).toBe(true)
  })

  it('失焦但文本未变（仍是 default_identity）时不触发保存', async () => {
    vi.mocked(fetchDialogueConfig).mockResolvedValue({
      config: {
        target_words: 3000,
        disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
        auto_build_character_count: 5, auto_build_chapter_count: 3,
        chat_identity: '',
      },
      default_identity: '内容包默认身份',
      buildtime_review_hooks: [],
      runtime_review_hooks: [],
    })
    renderPanel()
    const textarea = await screen.findByLabelText('对话agent 人物设定') as HTMLTextAreaElement
    fireEvent.blur(textarea)
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(putDialogueConfig).not.toHaveBeenCalled()
  })

  it('在 default_identity 基础上编辑后失焦，保存编辑后的完整文本', async () => {
    vi.mocked(fetchDialogueConfig).mockResolvedValue({
      config: {
        target_words: 3000,
        disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
        auto_build_character_count: 5, auto_build_chapter_count: 3,
        chat_identity: '',
      },
      default_identity: '内容包默认身份',
      buildtime_review_hooks: [],
      runtime_review_hooks: [],
    })
    renderPanel()
    const textarea = await screen.findByLabelText('对话agent 人物设定') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '内容包默认身份 + 追加设定' } })
    fireEvent.blur(textarea)
    await waitFor(() => {
      expect(putDialogueConfig.mock.calls.at(-1)?.[1]).toEqual({
        dialogue: { chat_identity: '内容包默认身份 + 追加设定' },
      })
    })
  })

  it('渲染文本识别小说导入配置字段', async () => {
    renderPanel()
    expect(await screen.findByLabelText('分片字数')).toBeTruthy()
    expect(screen.getByLabelText('压缩间隔')).toBeTruthy()
    expect(screen.getByLabelText('并发度')).toBeTruthy()
    expect(screen.getByLabelText('字数提醒阈值')).toBeTruthy()
    expect((screen.getByLabelText('压缩间隔') as HTMLInputElement).value).toBe('5')
  })

  it('修改压缩间隔失焦后保存到全局 config', async () => {
    renderPanel()
    const input = await screen.findByLabelText('压缩间隔') as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '8' } })
    fireEvent.blur(input)
    await waitFor(() => {
      expect(saveChronosConfig).toHaveBeenCalled()
      const lastCall = vi.mocked(saveChronosConfig).mock.calls.at(-1)?.[0]
      expect(lastCall?.novel_import?.compaction_interval).toBe(8)
    })
  })
})
