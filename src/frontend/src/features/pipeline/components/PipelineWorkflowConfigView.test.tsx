import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useNavigate } from 'react-router-dom'
import PipelineWorkflowConfigView from '@/features/pipeline/components/PipelineWorkflowConfigView'
import { renderWithClient } from '@/test/renderWithClient'

const RUNTIME_PATH = '/novel/default/pipeline'
const SKELETON_PATH = '/novel/default/pipeline?tab=skeleton'
const SANDBOX_PATH = '/novel/default/pipeline?tab=sandbox'

function WorkflowNavHarness() {
  const navigate = useNavigate()
  return (
    <>
      <button type="button" aria-label="go-sandbox" onClick={() => navigate('/novel/default/pipeline?tab=sandbox')} />
      <button type="button" aria-label="go-runtime" onClick={() => navigate('/novel/default/pipeline?tab=runtime')} />
      <PipelineWorkflowConfigView novelId="default" />
    </>
  )
}

function renderView(initialPath = RUNTIME_PATH, seedDialogueConfig = true) {
  return renderWithClient(
    <MemoryRouter initialEntries={[initialPath]}>
      <PipelineWorkflowConfigView novelId="default" />
    </MemoryRouter>,
    { seedDialogueConfig },
  )
}

vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ nodes, onNodeClick, onPaneClick }: {
    nodes: { id: string; data: { label: string; selected?: boolean; branch?: boolean } }[]
    onNodeClick?: (e: unknown, node: { id: string }) => void
    onPaneClick?: () => void
  }) => (
    <div data-testid="reactflow" onClick={() => onPaneClick?.()}>
      {nodes.map(n => (
        <div
          key={n.id}
          data-testid={`graph-node-${n.id}`}
          data-selected={n.data.selected ? 'true' : 'false'}
          data-branch={n.data.branch ? 'true' : 'false'}
          onClick={(e: React.MouseEvent) => { e.stopPropagation(); onNodeClick?.(e, n) }}
        >
          {n.data.label}
        </div>
      ))}
    </div>
  ),
  ReactFlowProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Background: () => null,
  Controls: () => null,
  useNodesState: (initial: unknown[]) => [initial, vi.fn(), vi.fn()],
  useNodesInitialized: () => true,
}))

vi.mock('@/features/pipeline/utils/authorLoopDialogueConfig', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/pipeline/utils/authorLoopDialogueConfig')>()
  return {
    ...actual,
    fetchDialogueConfig: vi.fn().mockResolvedValue({
      config: {
        target_words: 3000,
        disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
        disabled_setup_review_hooks: [],
        llm_params: {},
        sandbox_llm_params: {},
        import_llm_params: {},
        auto_build_character_count: 5,
        auto_build_chapter_count: 3,
        chat_identity: '',
      },
      default_identity: '',
      buildtime_review_hooks: [],
      runtime_review_hooks: [],
      setup_review_hooks: [],
    }),
    putDialogueConfig: vi.fn(),
  }
})

import { fetchDialogueConfig, putDialogueConfig } from '@/features/pipeline/utils/authorLoopDialogueConfig'

vi.mock('@/shared/utils/novels', () => ({
  listProseStyles: vi.fn().mockResolvedValue([]),
  getProseStyle: vi.fn().mockResolvedValue({ preset: 'plain-direct', custom_addendum: '' }),
  setProseStyle: vi.fn().mockResolvedValue({ ok: true }),
  getSandboxDialogueTurnCount: vi.fn().mockResolvedValue(null),
  setSandboxDialogueTurnCount: vi.fn().mockResolvedValue({ ok: true }),
}))

afterEach(() => cleanup())

describe('PipelineWorkflowConfigView workflow views', async () => {
  beforeEach(() => cleanup())

  it('页面内不渲染 workflow tab 切换条（改由顶栏流水线子菜单路由）', () => {
    renderView()
    expect(screen.queryByRole('tab', { name: '骨架扩写' })).toBeNull()
    expect(screen.queryByRole('tab', { name: '沙盒' })).toBeNull()
    expect(screen.queryByRole('tab', { name: '主笔运行时' })).toBeNull()
  })

  it('默认显示写作运行时图（导演节点），且采样参数悬浮面板默认不显示', async () => {
    renderView()
    expect(screen.getByTestId('reactflow').textContent).toContain('导演（一次直出定稿正文）')
    expect(screen.queryByText(/采样参数 ·/)).toBeNull()
  })

  it('写作运行时（主笔）tab 不渲染流水线配置面板', async () => {
    renderView()
    expect(screen.queryByText('流水线配置')).toBeNull()
  })

  it('写作运行时图以导演为入口节点', async () => {
    renderView(RUNTIME_PATH, false)
    const flow = screen.getByTestId('reactflow').textContent ?? ''
    expect(flow).toContain('导演（一次直出定稿正文）')
    expect(flow).not.toContain('细节强调（并发预处理反馈）')
    await waitFor(() => {
      expect(vi.mocked(fetchDialogueConfig)).toHaveBeenCalledWith('default')
    })
  })

  it('写作运行时图恰好三节点（导演/正文审核/角色状态推演），无死节点残留', async () => {
    renderView()
    const flow = screen.getByTestId('reactflow').textContent ?? ''
    expect(flow).toContain('正文审核')
    expect(flow).toContain('角色状态推演')
    expect(flow).not.toContain('文风守卫')
    expect(flow).not.toContain('状态守卫（同步自愈）')
    expect(flow).not.toContain('摘要')
  })

  it('?tab=skeleton 显示能力节点图（图片识别/文本识别节点）', async () => {
    renderView(SKELETON_PATH)
    expect(screen.getByText('图片识别')).toBeTruthy()
    expect(screen.getByText('文本识别')).toBeTruthy()
    expect(screen.queryByText('导演（一次直出定稿正文）')).toBeNull()
  })

  it('?tab=runtime 与 ?tab=skeleton 分别显示不同 workflow 图', async () => {
    renderView(SKELETON_PATH)
    expect(screen.queryByText('导演（一次直出定稿正文）')).toBeNull()
    cleanup()
    renderView(RUNTIME_PATH)
    expect(screen.getByTestId('reactflow').textContent).toContain('导演（一次直出定稿正文）')
  })

  it('?tab=sandbox 显示沙盒图（七节点，非写作运行时图）', async () => {
    renderView(SANDBOX_PATH)
    const flow = screen.getByTestId('reactflow')
    expect(flow.textContent).toContain('正文编写')
    expect(flow.textContent).toContain('联合台词草稿')
    expect(flow.textContent).toContain('在场角色识别（仅开场轮）')
    expect(flow.textContent).toContain('角色状态推演')
    expect(flow.textContent).toContain('场景状态推演')
    expect(flow.textContent).toContain('剧情摘要折叠')
    expect(flow.textContent).toContain('事件抽取')
    expect(flow.textContent).not.toContain('事件摘要折叠')
    expect(flow.textContent).toContain('角色档案演变')
    expect(flow.textContent).toContain('剧情选项建议')
    expect(flow.textContent).not.toContain('导演（一次直出定稿正文）')
    expect(flow.textContent).not.toContain('细节强调（并发预处理反馈）')
  })

  it('沙盒 workflow：dialogue_draft/identify_cast 节点可点选，面板无文风守卫', async () => {
    renderView(SANDBOX_PATH)
    fireEvent.click(screen.getByTestId('graph-node-dialogue_draft'))
    expect(screen.getByText('沙盒运行 · 联合台词草稿')).toBeTruthy()
    expect(screen.getByLabelText('联合台词草稿 temperature')).toBeTruthy()
    expect(screen.queryByText('文风守卫')).toBeNull()
    fireEvent.click(screen.getByTestId('graph-node-identify_cast'))
    expect(screen.getByText('沙盒运行 · 在场角色识别（仅开场轮）')).toBeTruthy()
    expect(screen.queryByText('文风守卫')).toBeNull()
  })

  it('沙盒 workflow：selection_rewrite 节点可点选，面板带文风守卫', async () => {
    renderView(SANDBOX_PATH)
    fireEvent.click(screen.getByTestId('graph-node-selection_rewrite'))
    expect(screen.getByText('沙盒运行 · 选中片段重写（按需触发）')).toBeTruthy()
    expect(screen.getByLabelText('选中片段重写（按需触发） temperature')).toBeTruthy()
    expect(screen.getByText('文风守卫')).toBeTruthy()
  })

  it('沙盒 workflow：derive_char 勾选并发开关写入 sandbox_llm_params', async () => {
    renderView(SANDBOX_PATH)
    fireEvent.click(screen.getByTestId('graph-node-derive_char'))
    const concurrentSwitch = await screen.findByRole('switch', { name: '并发推演角色状态' })
    fireEvent.click(concurrentSwitch)
    await waitFor(() => expect(vi.mocked(putDialogueConfig)).toHaveBeenCalled())
    expect(vi.mocked(putDialogueConfig).mock.calls.at(-1)?.[1]).toEqual({
      dialogue: { sandbox_llm_params: { derive_char: { concurrent: true } } },
    })
  })

  it('沙盒 workflow：summary_fold 与 event_extract 节点可点选并展示参数面板', async () => {
    renderView(SANDBOX_PATH)
    fireEvent.click(screen.getByTestId('graph-node-summary_fold'))
    expect(screen.getByText('沙盒运行 · 剧情摘要折叠')).toBeTruthy()
    expect(screen.getByLabelText('剧情摘要折叠 temperature')).toBeTruthy()
    fireEvent.click(screen.getByTestId('graph-node-event_extract'))
    expect(screen.getByText('沙盒运行 · 事件抽取')).toBeTruthy()
    expect(screen.getByLabelText('事件抽取 temperature')).toBeTruthy()
  })

  it('沙盒 workflow：默认不渲染节点参数面板', async () => {
    renderView(SANDBOX_PATH)
    expect(screen.queryByText(/沙盒运行 ·/)).toBeNull()
  })

  it('沙盒 workflow：点击图节点后展示对应参数面板', async () => {
    renderView(SANDBOX_PATH)
    fireEvent.click(screen.getByTestId('graph-node-prose'))
    expect(screen.getByText('沙盒运行 · 正文编写')).toBeTruthy()
    expect(screen.getByLabelText('正文编写 temperature')).toBeTruthy()
  })

  it('沙盒 workflow：再次点击已选中节点取消选中，面板隐藏', async () => {
    renderView(SANDBOX_PATH)
    fireEvent.click(screen.getByTestId('graph-node-prose'))
    expect(screen.getByText('沙盒运行 · 正文编写')).toBeTruthy()
    fireEvent.click(screen.getByTestId('graph-node-prose'))
    expect(screen.queryByText('沙盒运行 · 正文编写')).toBeNull()
  })

  it('沙盒 workflow：点击图空白处取消选中', async () => {
    renderView(SANDBOX_PATH)
    fireEvent.click(screen.getByTestId('graph-node-prose'))
    expect(screen.getByText('沙盒运行 · 正文编写')).toBeTruthy()
    fireEvent.click(screen.getByTestId('reactflow'))
    expect(screen.queryByText('沙盒运行 · 正文编写')).toBeNull()
  })

  it('切换 workflow（URL tab）后清空选中态', async () => {
    renderWithClient(
      <MemoryRouter initialEntries={[SANDBOX_PATH]}>
        <WorkflowNavHarness />
      </MemoryRouter>,
      { seedDialogueConfig: true },
    )
    fireEvent.click(screen.getByTestId('graph-node-prose'))
    expect(screen.getByText('沙盒运行 · 正文编写')).toBeTruthy()
    fireEvent.click(screen.getByLabelText('go-runtime'))
    expect(screen.queryByText(/沙盒运行 ·/)).toBeNull()
    expect(screen.queryByText(/采样参数 ·/)).toBeNull()
  })

  it('写作运行时 tab：点击导演节点展示对应参数面板', async () => {
    renderView()
    fireEvent.click(screen.getByTestId('graph-node-director'))
    expect(screen.getByText('采样参数 · 导演（一次直出定稿正文）')).toBeTruthy()
  })

  it('沙盒 workflow：右侧渲染台词草稿轮数面板', async () => {
    renderView(SANDBOX_PATH)
    expect(await screen.findByText('台词草稿轮数')).toBeTruthy()
    expect(screen.getByLabelText('台词草稿目标行数')).toBeTruthy()
  })

  it('skeleton workflow 含对话agent节点', async () => {
    renderView(SKELETON_PATH)
    expect(screen.getByText('对话agent')).toBeTruthy()
  })

  it('skeleton workflow：点击对话agent节点展示采样参数面板', async () => {
    renderView(SKELETON_PATH)
    fireEvent.click(screen.getByTestId('graph-node-chat_identity'))
    expect(screen.getByText('采样参数 · 对话agent')).toBeTruthy()
  })

  it('skeleton workflow：抽屉内文风/过渡审查采样参数按钮可打开参数面板', async () => {
    renderView(SKELETON_PATH)
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'Skill' }))
    const paramButtons = await screen.findAllByRole('button', { name: '采样参数' })
    fireEvent.click(paramButtons[0])
    expect(screen.getByText('采样参数 · 文风/过渡审查')).toBeTruthy()
  })

  it('skeleton workflow：点击一键建设定节点展示采样参数面板', async () => {
    renderView(SKELETON_PATH)
    // 图节点本身也叫「一键建设定」，与右侧 PipelineConfigPanel 的角色/章节数量小节同名——
    // 用 testid 定位图节点，不用文本，避免匹配到两处。
    expect(screen.getByTestId('graph-node-auto_build_setup')).toBeTruthy()
    fireEvent.click(screen.getByTestId('graph-node-auto_build_setup'))
    expect(screen.getByText('采样参数 · 一键建设定')).toBeTruthy()
  })

  it('skeleton workflow：点击角色档案自动推演节点展示采样参数面板', async () => {
    renderView(SKELETON_PATH)
    fireEvent.click(screen.getByTestId('graph-node-timeline_derive'))
    expect(screen.getByText('采样参数 · 角色档案自动推演')).toBeTruthy()
  })

  it('skeleton workflow 渲染流水线配置面板，含对话agent人物设定文本框', async () => {
    renderView(SKELETON_PATH)
    expect(await screen.findByText('流水线配置')).toBeTruthy()
    expect(screen.getByLabelText('对话agent 人物设定')).toBeTruthy()
  })

  it('selecting character_portrait renders ImageGenNodeParamsPanel not NodeLlmParamsPanel', async () => {
    renderView(SKELETON_PATH)
    fireEvent.click(screen.getByTestId('graph-node-character_portrait'))
    expect(await screen.findByText('生图模型 · 立绘生成')).toBeTruthy()
    expect(screen.queryByText('采样参数 · 立绘生成')).toBeNull()
  })
})
