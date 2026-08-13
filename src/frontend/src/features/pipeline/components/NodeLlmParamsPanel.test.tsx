import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react'
import NodeLlmParamsPanel from '@/features/pipeline/components/NodeLlmParamsPanel'
import { useModelRegistry } from '@/features/pipeline/queries/modelRegistry'
import { fetchDialogueConfig } from '@/features/pipeline/utils/authorLoopDialogueConfig'
import { renderWithClient } from '@/test/renderWithClient'

const putDialogueConfigMock = vi.fn()

const dialogueConfigState = {
  config: {
    target_words: 3000,
    disabled_buildtime_review_hooks: [] as string[], disabled_runtime_review_hooks: [] as string[],
    llm_params: {
      director: { temperature: 0.8 },
      state_derive: { enable_thinking: true, thinking_effort: 'high' as const },
    },
    sandbox_llm_params: { prose: { temperature: 0.7 } },
  },
  buildtime_review_hooks: [] as { name: string; display_name: string; axis: 'stage' | 'transition'; enabled: boolean }[],
  runtime_review_hooks: [] as { name: string; display_name: string; enabled: boolean }[],
}

vi.mock('@/features/pipeline/utils/authorLoopDialogueConfig', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/pipeline/utils/authorLoopDialogueConfig')>()
  return {
    ...actual,
    fetchDialogueConfig: vi.fn(async () => structuredClone(dialogueConfigState)),
    putDialogueConfig: vi.fn(async (_novelId: string, body: { dialogue?: Record<string, unknown> }) => {
      putDialogueConfigMock(body)
      const dialogue = body.dialogue
      if (dialogue?.llm_params && typeof dialogue.llm_params === 'object') {
        dialogueConfigState.config.llm_params = {
          ...dialogueConfigState.config.llm_params,
          ...(dialogue.llm_params as typeof dialogueConfigState.config.llm_params),
        }
      }
      if (dialogue?.sandbox_llm_params && typeof dialogue.sandbox_llm_params === 'object') {
        dialogueConfigState.config.sandbox_llm_params = {
          ...dialogueConfigState.config.sandbox_llm_params,
          ...(dialogue.sandbox_llm_params as typeof dialogueConfigState.config.sandbox_llm_params),
        }
      }
      return structuredClone(dialogueConfigState)
    }),
  }
})

vi.mock('@/features/pipeline/queries/modelRegistry', () => ({
  useModelRegistry: vi.fn(() => ({
    data: {
      cloudModels: [{ id: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash', provider: 'openai_compatible' }],
      customModels: [{ id: 'custom-1', label: '我的模型', provider: 'openai_compatible', base_url: 'https://x.example.com/v1', model: 'm1' }],
    },
  })),
}))

const RUNTIME_NODE_IDS = ['director', 'review', 'state_derive']
const RUNTIME_LABELS: Record<string, string> = {
  director: '导演（一次直出定稿正文）',
  review: '正文审核',
  state_derive: '角色状态推演',
}
const SANDBOX_NODE_IDS = ['prose', 'derive_char', 'derive_scene', 'summary_fold', 'event_extract', 'profile_mutate', 'suggest']
const SANDBOX_LABELS: Record<string, string> = {
  prose: '正文编写',
  derive_char: '角色状态推演',
  derive_scene: '场景状态推演',
  summary_fold: '剧情摘要折叠',
  event_extract: '事件抽取',
  profile_mutate: '角色档案演变',
  suggest: '剧情选项建议',
}

afterEach(() => {
  cleanup()
  putDialogueConfigMock.mockClear()
  vi.mocked(useModelRegistry).mockReturnValue({
    data: {
      cloudModels: [{ id: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash', provider: 'openai_compatible' }],
      customModels: [{ id: 'custom-1', label: '我的模型', provider: 'openai_compatible', base_url: 'https://x.example.com/v1', model: 'm1' }],
    },
  } as ReturnType<typeof useModelRegistry>)
  dialogueConfigState.config.llm_params = {
    director: { temperature: 0.8 },
    state_derive: { enable_thinking: true, thinking_effort: 'high' },
  }
  dialogueConfigState.config.sandbox_llm_params = { prose: { temperature: 0.7 } }
})

describe('NodeLlmParamsPanel', () => {
  it('selectedNodeId 为 null 时不渲染', () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={RUNTIME_NODE_IDS} labels={RUNTIME_LABELS} configKey="llm_params"
        title="采样参数" hint="选节点，逐项配置采样参数" selectedNodeId={null} novelId="default"
      />,
    )
    expect(screen.queryByText('temperature')).toBeNull()
  })

  it('selectedNodeId 不在 nodeIds 里时不渲染', () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={RUNTIME_NODE_IDS} labels={RUNTIME_LABELS} configKey="llm_params"
        title="采样参数" hint="选节点，逐项配置采样参数" selectedNodeId="not-a-runtime-node" novelId="default"
      />,
    )
    expect(screen.queryByText('temperature')).toBeNull()
  })

  it('运行时：选中 director 后展示其采样参数，调参数走 llm_params', async () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={RUNTIME_NODE_IDS} labels={RUNTIME_LABELS} configKey="llm_params"
        title="采样参数" hint="选节点，逐项配置采样参数" selectedNodeId="director" novelId="default"
      />,
    )
    expect(await screen.findByText('0.80')).toBeTruthy()
    const slider = screen.getByLabelText('导演（一次直出定稿正文） temperature')
    fireEvent.change(slider, { target: { value: '1.1' } })
    await waitFor(() => expect(putDialogueConfigMock).toHaveBeenCalled())
    expect(putDialogueConfigMock.mock.calls[0][0]).toEqual({
      dialogue: {
        llm_params: {
          director: { temperature: 1.1 },
          state_derive: { enable_thinking: true, thinking_effort: 'high' },
        },
      },
    })
  })

  it('沙盒：选中 prose 后展示其采样参数，调参数走 sandbox_llm_params', async () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={SANDBOX_NODE_IDS} labels={SANDBOX_LABELS} configKey="sandbox_llm_params"
        title="沙盒运行" hint="选节点，逐项配置采样参数" selectedNodeId="prose" novelId="default"
      />,
    )
    expect(await screen.findByText('0.70')).toBeTruthy()
    const slider = screen.getByLabelText('正文编写 temperature')
    fireEvent.change(slider, { target: { value: '0.95' } })
    await waitFor(() => expect(putDialogueConfigMock).toHaveBeenCalled())
    expect(putDialogueConfigMock.mock.calls[0][0]).toEqual({
      dialogue: { sandbox_llm_params: { prose: { temperature: 0.95 } } },
    })
  })

  it('运行时：选中 review 节点，未配置的参数显示"未设置"', async () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={RUNTIME_NODE_IDS} labels={RUNTIME_LABELS} configKey="llm_params"
        title="采样参数" hint="选节点，逐项配置采样参数" selectedNodeId="review" novelId="default"
      />,
    )
    expect((await screen.findAllByText('未设置（沿用全局默认）')).length).toBeGreaterThan(0)
  })

  it('点"恢复默认"清掉该字段', async () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={RUNTIME_NODE_IDS} labels={RUNTIME_LABELS} configKey="llm_params"
        title="采样参数" hint="选节点，逐项配置采样参数" selectedNodeId="director" novelId="default"
      />,
    )
    await screen.findByText('0.80')
    const resetButtons = screen.getAllByRole('button', { name: '恢复默认' })
    fireEvent.click(resetButtons[0])
    await waitFor(() => expect(putDialogueConfigMock).toHaveBeenCalled())
    expect(putDialogueConfigMock.mock.calls[0][0]).toEqual({
      dialogue: {
        llm_params: {
          director: {},
          state_derive: { enable_thinking: true, thinking_effort: 'high' },
        },
      },
    })
  })

  it('未配置时按节点默认策略显示开启或关闭', async () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={RUNTIME_NODE_IDS} labels={RUNTIME_LABELS} configKey="llm_params"
        title="采样参数" hint="选节点，逐项配置采样参数" selectedNodeId="director" novelId="default"
      />,
    )
    await screen.findByText('0.80')
    expect((screen.getByRole('radio', { name: '开启' }) as HTMLInputElement).checked).toBe(true)
    expect((screen.getByRole('radio', { name: '关闭' }) as HTMLInputElement).checked).toBe(false)

    cleanup()
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={RUNTIME_NODE_IDS} labels={RUNTIME_LABELS} configKey="llm_params"
        title="采样参数" hint="选节点，逐项配置采样参数" selectedNodeId="review" novelId="default"
      />,
    )
    expect((await screen.findByRole('radio', { name: '关闭' }) as HTMLInputElement).checked).toBe(true)
  })

  it('选"开启"（此前未配置）默认写入 medium 档位', async () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={RUNTIME_NODE_IDS} labels={RUNTIME_LABELS} configKey="llm_params"
        title="采样参数" hint="选节点，逐项配置采样参数" selectedNodeId="review" novelId="default"
      />,
    )
    fireEvent.click(await screen.findByRole('radio', { name: '开启' }))
    await waitFor(() => expect(putDialogueConfigMock).toHaveBeenCalled())
    expect(putDialogueConfigMock.mock.calls[0][0]).toEqual({
      dialogue: {
        llm_params: {
          director: { temperature: 0.8 },
          review: { enable_thinking: true, thinking_effort: 'medium' },
          state_derive: { enable_thinking: true, thinking_effort: 'high' },
        },
      },
    })
  })

  it('点选"开启"后单选框立即反映选中，不等保存请求 round-trip 完成（回归：受控输入抖回原值导致"点击没反应"）', async () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={RUNTIME_NODE_IDS} labels={RUNTIME_LABELS} configKey="llm_params"
        title="采样参数" hint="选节点，逐项配置采样参数" selectedNodeId="review" novelId="default"
      />,
    )
    const onRadio = await screen.findByRole('radio', { name: '开启' }) as HTMLInputElement
    expect(onRadio.checked).toBe(false)
    fireEvent.click(onRadio)
    // Assert synchronously, before the save mutation's promise resolves -- without a
    // local override the `checked` prop stays bound to the stale cfg value until the
    // PUT round-trip's refetch completes, so the radio would visually snap back to
    // unselected right after the click (the reported "点击没反应" symptom).
    expect(onRadio.checked).toBe(true)
  })

  it('已开启 thinking 的节点：单选框预填"开启"且档位可见，选"关闭"后写入 enable_thinking: false（不是清空回默认）', async () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={RUNTIME_NODE_IDS} labels={RUNTIME_LABELS} configKey="llm_params"
        title="采样参数" hint="选节点，逐项配置采样参数" selectedNodeId="state_derive" novelId="default"
      />,
    )
    expect((await screen.findByRole('radio', { name: '开启' }) as HTMLInputElement).checked).toBe(true)
    fireEvent.click(screen.getByRole('radio', { name: '关闭' }))
    await waitFor(() => expect(putDialogueConfigMock).toHaveBeenCalled())
    // 关键点：必须显式写 enable_thinking: false，而不是清空成 {} ——对 DeepSeek 这类
    // default_thinking_enabled=True 的 provider，清空等于什么都没关（沿用默认开启）。
    expect(putDialogueConfigMock.mock.calls[0][0]).toEqual({
      dialogue: {
        llm_params: {
          state_derive: { enable_thinking: false },
          director: { temperature: 0.8 },
        },
      },
    })
  })

  it('切换 novelId 时清空 localOverrides，避免上一本小说的 thinking 状态泄漏', async () => {
    const panel = (novelId: string) => (
      <NodeLlmParamsPanel
        nodeIds={RUNTIME_NODE_IDS} labels={RUNTIME_LABELS} configKey="llm_params"
        title="采样参数" hint="选节点，逐项配置采样参数" selectedNodeId="state_derive" novelId={novelId}
      />
    )
    const { rerender } = renderWithClient(panel('novel-a'))
    expect((await screen.findByRole('radio', { name: '开启' }) as HTMLInputElement).checked).toBe(true)
    fireEvent.click(screen.getByRole('radio', { name: '关闭' }))
    await waitFor(() => expect(putDialogueConfigMock).toHaveBeenCalled())

    dialogueConfigState.config.llm_params = { director: { temperature: 0.8 } }
    rerender(panel('novel-b'))
    expect((await screen.findByRole('radio', { name: '关闭' }) as HTMLInputElement).checked).toBe(true)
  })
})

describe('NodeLlmParamsPanel model_ref override', () => {
  it('模型选择器默认收起——未配置时 combobox 显示 placeholder，列表不渲染', async () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={SANDBOX_NODE_IDS} labels={SANDBOX_LABELS} configKey="sandbox_llm_params"
        title="沙盒运行" hint="选节点，逐项配置采样参数" selectedNodeId="prose" novelId="default"
      />,
    )
    await screen.findByPlaceholderText('跟随全局默认')
    expect(screen.queryByText('DeepSeek V4 Flash')).toBeNull()
  })

  it('展开 combobox 列表，未配置 model_ref 时不预选任何一条', async () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={SANDBOX_NODE_IDS} labels={SANDBOX_LABELS} configKey="sandbox_llm_params"
        title="沙盒运行" hint="选节点，逐项配置采样参数" selectedNodeId="prose" novelId="default"
      />,
    )
    await screen.findByPlaceholderText('跟随全局默认')
    const group = screen.getByPlaceholderText('跟随全局默认').closest('[data-slot="input-group"]') as HTMLElement
    fireEvent.click(within(group).getAllByRole('button')[0])
    await screen.findByText('DeepSeek V4 Flash')
    expect(screen.queryByRole('option', { name: '我的模型', selected: true })).toBeNull()
  })

  it('选中一条自定义模型后写入 model_ref', async () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={SANDBOX_NODE_IDS} labels={SANDBOX_LABELS} configKey="sandbox_llm_params"
        title="沙盒运行" hint="选节点，逐项配置采样参数" selectedNodeId="prose" novelId="default"
      />,
    )
    await screen.findByPlaceholderText('跟随全局默认')
    const group = screen.getByPlaceholderText('跟随全局默认').closest('[data-slot="input-group"]') as HTMLElement
    fireEvent.click(within(group).getAllByRole('button')[0])
    fireEvent.click(await screen.findByRole('option', { name: '我的模型' }))
    await waitFor(() => expect(putDialogueConfigMock).toHaveBeenCalled())
    expect(putDialogueConfigMock.mock.calls[0][0]).toEqual({
      dialogue: { sandbox_llm_params: { prose: { temperature: 0.7, model_ref: 'custom-1' } } },
    })
    expect((screen.getByPlaceholderText('跟随全局默认') as HTMLInputElement).value).toBe('我的模型')
  })

  it('自定义模型 label 为空时显示 model 字段而非 id', async () => {
    vi.mocked(useModelRegistry).mockReturnValue({
      data: {
        cloudModels: [],
        customModels: [{
          id: 'custom-1', label: '', provider: 'openai_compatible',
          base_url: 'https://x.example.com/v1', model: 'deepseek-chat',
        }],
      },
    } as ReturnType<typeof useModelRegistry>)
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={SANDBOX_NODE_IDS} labels={SANDBOX_LABELS} configKey="sandbox_llm_params"
        title="沙盒运行" hint="选节点，逐项配置采样参数" selectedNodeId="prose" novelId="default"
      />,
    )
    await screen.findByPlaceholderText('跟随全局默认')
    const group = screen.getByPlaceholderText('跟随全局默认').closest('[data-slot="input-group"]') as HTMLElement
    fireEvent.click(within(group).getAllByRole('button')[0])
    fireEvent.click(await screen.findByRole('option', { name: 'deepseek-chat' }))
    await waitFor(() => expect(putDialogueConfigMock).toHaveBeenCalled())
    expect((screen.getByPlaceholderText('跟随全局默认') as HTMLInputElement).value).toBe('deepseek-chat')
  })

  it('恢复默认清掉 model_ref', async () => {
    vi.mocked(fetchDialogueConfig).mockResolvedValueOnce({
      config: {
        target_words: 3000,
        disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
        llm_params: {},
        sandbox_llm_params: { prose: { temperature: 0.7, model_ref: 'custom-1' } },
      },
      buildtime_review_hooks: [], runtime_review_hooks: [],
    })
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={SANDBOX_NODE_IDS} labels={SANDBOX_LABELS} configKey="sandbox_llm_params"
        title="沙盒运行" hint="选节点，逐项配置采样参数" selectedNodeId="prose" novelId="default"
      />,
    )
    await screen.findByDisplayValue('我的模型')
    const resetButtons = screen.getAllByRole('button', { name: '恢复默认' })
    fireEvent.click(resetButtons[resetButtons.length - 1])
    await waitFor(() => expect(putDialogueConfigMock).toHaveBeenCalled())
    expect(putDialogueConfigMock.mock.calls[0][0]).toEqual({
      dialogue: { sandbox_llm_params: { prose: { temperature: 0.7 } } },
    })
  })
})

describe('NodeLlmParamsPanel style guard toggle', () => {
  it('styleGuardNodeIds 不含当前节点时不渲染开关', async () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={RUNTIME_NODE_IDS} labels={RUNTIME_LABELS} configKey="llm_params"
        title="采样参数" hint="选节点，逐项配置采样参数" selectedNodeId="review" novelId="default"
        styleGuardNodeIds={new Set(['director'])}
      />,
    )
    await screen.findAllByText('未设置（沿用全局默认）')
    expect(screen.queryByText('文风守卫')).toBeNull()
  })

  it('styleGuardNodeIds 含当前节点时渲染开关，勾选走 disable_style_guard 字段', async () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={RUNTIME_NODE_IDS} labels={RUNTIME_LABELS} configKey="llm_params"
        title="采样参数" hint="选节点，逐项配置采样参数" selectedNodeId="director" novelId="default"
        styleGuardNodeIds={new Set(['director'])}
      />,
    )
    await screen.findByText('0.80')
    const styleGuardSwitch = screen.getByRole('switch', { name: '跳过禁用词/句式守卫' })
    expect(styleGuardSwitch.getAttribute('aria-checked')).toBe('false')
    fireEvent.click(styleGuardSwitch)
    await waitFor(() => expect(putDialogueConfigMock).toHaveBeenCalled())
    expect(putDialogueConfigMock.mock.calls[0][0]).toEqual({
      dialogue: {
        llm_params: {
          director: { temperature: 0.8, disable_style_guard: true },
          state_derive: { enable_thinking: true, thinking_effort: 'high' },
        },
      },
    })
  })

  it('恢复默认清掉 disable_style_guard 字段', async () => {
    vi.mocked(fetchDialogueConfig).mockResolvedValueOnce({
      config: {
        target_words: 3000,
        disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
        llm_params: { director: { temperature: 0.8, disable_style_guard: true } },
        sandbox_llm_params: {},
      },
      buildtime_review_hooks: [], runtime_review_hooks: [],
    })
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={RUNTIME_NODE_IDS} labels={RUNTIME_LABELS} configKey="llm_params"
        title="采样参数" hint="选节点，逐项配置采样参数" selectedNodeId="director" novelId="default"
        styleGuardNodeIds={new Set(['director'])}
      />,
    )
    const styleGuardSwitch = await screen.findByRole('switch', { name: '跳过禁用词/句式守卫' })
    expect(styleGuardSwitch.getAttribute('aria-checked')).toBe('true')
    const resetButtons = screen.getAllByRole('button', { name: '恢复默认' })
    fireEvent.click(resetButtons[resetButtons.length - 1])
    await waitFor(() => expect(putDialogueConfigMock).toHaveBeenCalled())
    expect(putDialogueConfigMock.mock.calls[0][0]).toEqual({
      dialogue: { llm_params: { director: { temperature: 0.8 } } },
    })
  })
})

const SANDBOX_STYLE_GUARD_NODE_IDS = new Set([
  'prose', 'derive_char', 'derive_scene', 'event_log', 'profile_mutate', 'suggest',
])
const SANDBOX_NODE_IDS_EXTENDED = [...SANDBOX_NODE_IDS, 'dialogue_draft', 'identify_cast']
const SANDBOX_LABELS_EXTENDED: Record<string, string> = {
  ...SANDBOX_LABELS,
  dialogue_draft: '联合台词草稿',
  identify_cast: '在场角色识别（仅开场轮）',
}

describe('NodeLlmParamsPanel sandbox extended nodes', () => {
  it('dialogue_draft 节点不渲染文风守卫开关', async () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={SANDBOX_NODE_IDS_EXTENDED} labels={SANDBOX_LABELS_EXTENDED}
        configKey="sandbox_llm_params" title="沙盒运行" hint="选节点，逐项配置采样参数"
        selectedNodeId="dialogue_draft" novelId="default"
        styleGuardNodeIds={SANDBOX_STYLE_GUARD_NODE_IDS}
      />,
    )
    await screen.findByLabelText('联合台词草稿 temperature')
    expect(screen.queryByText('文风守卫')).toBeNull()
  })

  it('derive_char 勾选并发开关写入 concurrent 字段', async () => {
    renderWithClient(
      <NodeLlmParamsPanel
        nodeIds={SANDBOX_NODE_IDS_EXTENDED} labels={SANDBOX_LABELS_EXTENDED}
        configKey="sandbox_llm_params" title="沙盒运行" hint="选节点，逐项配置采样参数"
        selectedNodeId="derive_char" novelId="default"
        styleGuardNodeIds={SANDBOX_STYLE_GUARD_NODE_IDS}
      />,
    )
    const concurrentSwitch = await screen.findByRole('switch', { name: '并发推演角色状态' })
    fireEvent.click(concurrentSwitch)
    await waitFor(() => expect(putDialogueConfigMock).toHaveBeenCalled())
    expect(putDialogueConfigMock.mock.calls[0][0]).toEqual({
      dialogue: { sandbox_llm_params: { prose: { temperature: 0.7 }, derive_char: { concurrent: true } } },
    })
  })
})
