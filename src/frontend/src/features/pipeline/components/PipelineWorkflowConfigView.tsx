import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  useNodesState,
  useNodesInitialized,
  type Node,
  type Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import MechanismStageNode from '@/features/pipeline/components/MechanismStageNode'
import DialogueDirectorNode from '@/features/pipeline/components/DialogueDirectorNode'
import ReviewSkillDropNode from '@/features/pipeline/components/ReviewSkillDropNode'
import NodeLlmParamsPanel from '@/features/pipeline/components/NodeLlmParamsPanel'
import ImageGenNodeParamsPanel from '@/features/pipeline/components/ImageGenNodeParamsPanel'
import PipelineConfigPanel from '@/features/pipeline/components/PipelineConfigPanel'
import SandboxDialogueTurnCountPanel from '@/features/pipeline/components/SandboxDialogueTurnCountPanel'
import AuthorLoopConfigPanel from '@/features/pipeline/components/AuthorLoopConfigPanel'
import { PanelRightIcon } from 'lucide-react'
import { Button } from '@/shared/components/ui/button'
import {
  SidebarInset,
  SidebarProvider,
  useSidebar,
} from '@/shared/components/ui/sidebar'
import {
  DIALOGUE_LOOP_STAGES,
  DIALOGUE_STAGE_EDGES,
  type DialogueStageDef,
  type DialogueStageEdge,
} from '@/shared/utils/dialogueLoopStages'
import {
  SKELETON_EXPANSION_STAGES,
  SKELETON_EXPANSION_EDGES,
} from '@/features/pipeline/utils/skeletonExpansionStages'
import { SANDBOX_RUN_STAGES, SANDBOX_RUN_EDGES } from '@/features/pipeline/utils/runStages'
import { useTheme } from '@/shared/hooks/useTheme'
import { workflowTabFromSearch, type WorkflowTab } from '@/shared/utils/novelRoute'

const nodeTypes = {
  mechanism: MechanismStageNode,
  'agent-config': DialogueDirectorNode,
  review: ReviewSkillDropNode,
}

const GAP_X = 72
const BRANCH_GAP_Y = 40
const CENTER_Y = 0
const FALLBACK_W = 190
const FALLBACK_H = 64

function SidePanelToggleButton() {
  const { toggleSidebar } = useSidebar()
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      aria-label="收起/展开侧边面板"
      onClick={toggleSidebar}
      className="absolute top-3 right-3 z-10 size-7 shadow-float bg-[var(--c-surface)]"
    >
      <PanelRightIcon className="size-4" />
    </Button>
  )
}

function CenteredFlow({
  baseNodes, edges, gridColor, selectableNodeIds, selectedNodeId, onSelectNode, novelId,
}: {
  baseNodes: Node[]
  edges: Edge[]
  gridColor: string
  selectableNodeIds: Set<string>
  selectedNodeId: string | null
  onSelectNode: (id: string | null) => void
  novelId: string
}) {
  const [nodes, setNodes, onNodesChange] = useNodesState(baseNodes)
  const initialized = useNodesInitialized()

  useEffect(() => {
    setNodes(prev => {
      const posById = new Map(prev.map(n => [n.id, n.position]))
      return baseNodes.map(n => ({ ...n, position: posById.get(n.id) ?? n.position }))
    })
  }, [baseNodes, setNodes])

  const sizeSig = nodes
    .map(n => `${n.id}:${Math.round(n.measured?.width ?? 0)}x${Math.round(n.measured?.height ?? 0)}`)
    .join('|')

  useEffect(() => {
    if (!initialized) return
    setNodes(prev => {
      const byId = new Map(prev.map(n => [n.id, n]))
      const mainNodes = baseNodes.filter(n => !n.data?.branch)
      const branchNodes = baseNodes.filter(n => n.data?.branch)
      const branchSourceOf = new Map(
        branchNodes.map(n => [n.id, edges.find(e => e.target === n.id)?.source]),
      )

      const resolved = mainNodes.map(base => byId.get(base.id) ?? base)
      const sizeOf = (n: Node) => ({
        w: n.measured?.width ?? FALLBACK_W,
        h: n.measured?.height ?? FALLBACK_H,
      })

      // Column (x-rank): explicit data.col when a stage declares one (parallel
      // fan-out/fan-in tracks share a column, see runStages.ts), else sequential
      // array order -- preserves the plain single-line layout the other tabs use.
      let autoCol = 0
      const colOf = new Map<string, number>()
      for (const n of resolved) {
        const explicit = n.data?.col
        const col = typeof explicit === 'number' ? explicit : autoCol
        colOf.set(n.id, col)
        if (typeof explicit !== 'number') autoCol++
      }
      const cols = [...new Set(colOf.values())].sort((a, b) => a - b)
      const colX = new Map<number, number>()
      let x = 0
      for (const col of cols) {
        colX.set(col, x)
        const widths = resolved.filter(n => colOf.get(n.id) === col).map(n => sizeOf(n).w)
        x += Math.max(...widths) + GAP_X
      }

      // Lane (row): explicit data.lane, default 0 (center line). Parallel tracks
      // that still progress along the x-axis get their own lane instead of being
      // parked below their source like `branch` nodes are.
      const laneOf = new Map<string, number>(resolved.map(n => [n.id, (n.data?.lane as number | undefined) ?? 0]))
      const laneStep = Math.max(...resolved.map(n => sizeOf(n).h)) + BRANCH_GAP_Y

      let changed = false
      const laidMain = resolved.map(n => {
        const { h } = sizeOf(n)
        const lane = laneOf.get(n.id) ?? 0
        const position = { x: colX.get(colOf.get(n.id) ?? 0) ?? 0, y: CENTER_Y + lane * laneStep - h / 2 }
        if (n.position.x !== position.x || n.position.y !== position.y) changed = true
        return { ...n, position }
      })
      const mainById = new Map(laidMain.map(n => [n.id, n]))

      // 旁支节点（如异步守卫）不占主链路 x 位，贴着其上游节点正下方，视觉上表示"分支出去、不阻塞主链路"。
      const branchIndexBySource = new Map<string, number>()
      const laidBranch = branchNodes.map(base => {
        const n = byId.get(base.id) ?? base
        const sourceId = branchSourceOf.get(base.id) ?? ''
        const sourceNode = mainById.get(sourceId)
        const sourceH = sourceNode?.measured?.height ?? FALLBACK_H
        const nodeH = n.measured?.height ?? FALLBACK_H
        const branchIndex = branchIndexBySource.get(sourceId) ?? 0
        branchIndexBySource.set(sourceId, branchIndex + 1)
        const position = {
          x: sourceNode?.position.x ?? 0,
          y: (sourceNode?.position.y ?? -sourceH / 2) + sourceH + BRANCH_GAP_Y + branchIndex * (nodeH + BRANCH_GAP_Y),
        }
        if (n.position.x !== position.x || n.position.y !== position.y) changed = true
        return { ...n, position }
      })

      return changed ? [...laidMain, ...laidBranch] : prev
    })
  }, [sizeSig, initialized, baseNodes, edges, setNodes])

  const displayNodes = nodes.map(n => (
    { ...n, data: { ...n.data, selected: n.id === selectedNodeId, novelId } }
  ))

  return (
    <ReactFlow
      nodes={displayNodes}
      edges={edges}
      onNodesChange={onNodesChange}
      nodeTypes={nodeTypes}
      defaultEdgeOptions={{ type: 'straight' }}
      nodesConnectable={false}
      nodesDraggable={false}
      onNodeClick={(_, node) => {
        if (!selectableNodeIds.has(node.id)) return
        onSelectNode(node.id === selectedNodeId ? null : node.id)
      }}
      onPaneClick={() => onSelectNode(null)}
      fitView
      fitViewOptions={{ padding: 0.12 }}
      proOptions={{ hideAttribution: true }}
    >
      <Background color={gridColor} gap={20} />
      <Controls showInteractive={false} />
    </ReactFlow>
  )
}

function buildNodes(stages: DialogueStageDef[]): Node[] {
  return stages.map(s => {
    if (s.kind === 'agent-config') {
      return {
        id: s.id,
        type: 'agent-config',
        position: s.position,
        draggable: false,
        data: { label: s.label, hint: s.hint, branch: s.branch ?? false, col: s.col, lane: s.lane },
      }
    }
    if (s.kind === 'review') {
      return {
        id: s.id,
        type: 'review',
        position: s.position,
        draggable: false,
        data: {
          label: s.label, group: s.reviewGroup ?? 'buildtime',
          branch: s.branch ?? false, col: s.col, lane: s.lane,
        },
      }
    }
    return {
      id: s.id,
      type: 'mechanism',
      position: s.position,
      draggable: false,
      data: { label: s.label, async: s.async ?? false, branch: s.branch ?? false, col: s.col, lane: s.lane },
    }
  })
}

function buildEdges(stageEdges: DialogueStageEdge[]): Edge[] {
  return stageEdges.map(e => ({
    id: `${e.source}->${e.target}${e.sourceHandle ? `:${e.sourceHandle}` : ''}${e.targetHandle ? `:>${e.targetHandle}` : ''}`,
    source: e.source,
    target: e.target,
    sourceHandle: e.sourceHandle,
    targetHandle: e.targetHandle,
    type: 'straight',
    label: e.async ? '异步' : undefined,
    style: e.async ? { strokeDasharray: '4 3', stroke: '#94a3b8' } : undefined,
  }))
}

export default function PipelineWorkflowConfigView({ novelId }: { novelId: string }) {
  const { darkMode } = useTheme()
  const gridColor = darkMode ? '#243044' : '#e2e8f0'
  const [searchParams] = useSearchParams()
  const tab = workflowTabFromSearch(searchParams.toString())
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  useEffect(() => setSelectedNodeId(null), [tab])

  const runtimeNodes = useMemo(() => buildNodes(DIALOGUE_LOOP_STAGES), [])
  const runtimeEdges = useMemo(() => buildEdges(DIALOGUE_STAGE_EDGES), [])
  const skeletonNodes = useMemo(() => buildNodes(SKELETON_EXPANSION_STAGES), [])
  const skeletonEdges = useMemo(() => buildEdges(SKELETON_EXPANSION_EDGES), [])
  const sandboxNodes = useMemo(() => buildNodes(SANDBOX_RUN_STAGES), [])
  const sandboxEdges = useMemo(() => buildEdges(SANDBOX_RUN_EDGES), [])

  const STAGE_BY_TAB: Record<WorkflowTab, { nodes: Node[]; edges: Edge[] }> = {
    runtime: { nodes: runtimeNodes, edges: runtimeEdges },
    skeleton: { nodes: skeletonNodes, edges: skeletonEdges },
    sandbox: { nodes: sandboxNodes, edges: sandboxEdges },
  }
  const baseNodes = STAGE_BY_TAB[tab].nodes
  const edges = STAGE_BY_TAB[tab].edges

  const RUNTIME_LLM_PARAM_NODE_IDS = ['director', 'review', 'state_derive']
  const SANDBOX_LLM_PARAM_NODE_IDS = [
    'prose', 'derive_char', 'derive_scene', 'summary_fold', 'event_extract', 'profile_mutate', 'suggest',
    'dialogue_draft', 'identify_cast', 'selection_rewrite',
  ]
  const SANDBOX_STYLE_GUARD_NODE_IDS = new Set([
    'prose', 'derive_char', 'derive_scene', 'summary_fold', 'event_extract', 'profile_mutate', 'suggest',
    'selection_rewrite',
  ])
  const IMPORT_LLM_PARAM_NODE_IDS = [
    'image_recognition', 'auto_build_setup', 'text_recognition', 'chat_identity', 'review',
    'timeline_derive', 'setup_quality_review',
    'skeleton_writer', 'beat_dialogue_draft', 'prose_style_extraction', 'incremental_relationship',
  ]
  const IMAGE_GEN_PARAM_NODE_IDS = ['character_portrait']
  const SANDBOX_IMAGE_GEN_PARAM_NODE_IDS = ['scene_image']
  const RUNTIME_IMAGE_GEN_PARAM_NODE_IDS = ['scene_image']
  const SELECTABLE_NODE_IDS_BY_TAB: Record<WorkflowTab, Set<string>> = {
    runtime: new Set([...RUNTIME_LLM_PARAM_NODE_IDS, ...RUNTIME_IMAGE_GEN_PARAM_NODE_IDS]),
    skeleton: new Set([...IMPORT_LLM_PARAM_NODE_IDS, ...IMAGE_GEN_PARAM_NODE_IDS]),
    sandbox: new Set([...SANDBOX_LLM_PARAM_NODE_IDS, ...SANDBOX_IMAGE_GEN_PARAM_NODE_IDS]),
  }

  const RUNTIME_LLM_PARAM_LABELS: Record<string, string> = {
    director: '导演（一次直出定稿正文）',
    review: '正文审核',
    state_derive: '角色状态推演',
  }
  const SANDBOX_LLM_PARAM_LABELS: Record<string, string> = {
    prose: '正文编写',
    derive_char: '角色状态推演',
    derive_scene: '场景状态推演',
    summary_fold: '剧情摘要折叠',
    event_extract: '事件抽取',
    profile_mutate: '角色档案演变',
    suggest: '剧情选项建议',
    dialogue_draft: '联合台词草稿',
    identify_cast: '在场角色识别（仅开场轮）',
    selection_rewrite: '选中片段重写（按需触发）',
  }
  const IMPORT_LLM_PARAM_LABELS: Record<string, string> = {
    image_recognition: '图片识别', auto_build_setup: '一键建设定', text_recognition: '文本识别',
    chat_identity: '对话agent', review: '文风/过渡审查', timeline_derive: '角色档案自动推演',
    setup_quality_review: '设定质量审查',
    skeleton_writer: '分拍底稿生成', beat_dialogue_draft: '拍台词草稿',
    prose_style_extraction: '文风抽取', incremental_relationship: '关系推断',
  }
  const IMAGE_GEN_PARAM_LABELS: Record<string, string> = { character_portrait: '立绘生成' }
  const SANDBOX_IMAGE_GEN_PARAM_LABELS: Record<string, string> = { scene_image: '场景生图' }
  const RUNTIME_IMAGE_GEN_PARAM_LABELS: Record<string, string> = { scene_image: '场景生图' }

  return (
    // contain-layout gives this box its own containing block for `position: fixed`
    // descendants (the right-side Sidebar uses `fixed inset-y-0`), so it's bounded
    // to this container instead of the real viewport and can't render under the
    // app's top navigation bar.
    <div className="w-full h-full flex flex-col contain-layout">
      <SidebarProvider
        defaultOpen
        className="flex h-full min-h-0 w-full"
        style={{ '--sidebar-width': '18rem' } as CSSProperties}
      >
        <div className="flex flex-1 min-h-0 w-full">
          <SidebarInset className="min-h-0 flex-1 overflow-hidden bg-transparent p-0">
            <div className="flex-1 relative h-full min-h-0">
              <SidePanelToggleButton />
              <ReactFlowProvider>
                <CenteredFlow
                  key={tab}
                  baseNodes={baseNodes}
                  edges={edges}
                  gridColor={gridColor}
                  selectableNodeIds={SELECTABLE_NODE_IDS_BY_TAB[tab]}
                  selectedNodeId={selectedNodeId}
                  onSelectNode={setSelectedNodeId}
                  novelId={novelId}
                />
              </ReactFlowProvider>
              {tab === 'runtime' && (
                <NodeLlmParamsPanel
                  nodeIds={RUNTIME_LLM_PARAM_NODE_IDS}
                  labels={RUNTIME_LLM_PARAM_LABELS}
                  configKey="llm_params"
                  title="采样参数"
                  hint="选节点，逐项配置采样参数"
                  selectedNodeId={selectedNodeId}
                  styleGuardNodeIds={new Set(['director'])}
                  novelId={novelId}
                />
              )}
              {tab === 'runtime' && (
                <ImageGenNodeParamsPanel
                  nodeIds={RUNTIME_IMAGE_GEN_PARAM_NODE_IDS}
                  labels={RUNTIME_IMAGE_GEN_PARAM_LABELS}
                  configKey="llm_params"
                  selectedNodeId={selectedNodeId}
                  novelId={novelId}
                />
              )}
              {tab === 'sandbox' && (
                <NodeLlmParamsPanel
                  nodeIds={SANDBOX_LLM_PARAM_NODE_IDS}
                  labels={SANDBOX_LLM_PARAM_LABELS}
                  configKey="sandbox_llm_params"
                  title="沙盒运行"
                  hint="选节点，逐项配置采样参数"
                  selectedNodeId={selectedNodeId}
                  styleGuardNodeIds={SANDBOX_STYLE_GUARD_NODE_IDS}
                  novelId={novelId}
                />
              )}
              {tab === 'skeleton' && (
                <NodeLlmParamsPanel
                  nodeIds={IMPORT_LLM_PARAM_NODE_IDS}
                  labels={IMPORT_LLM_PARAM_LABELS}
                  configKey="import_llm_params"
                  title="采样参数"
                  hint="选节点，逐项配置采样参数"
                  selectedNodeId={selectedNodeId}
                  novelId={novelId}
                />
              )}
              {tab === 'skeleton' && (
                <ImageGenNodeParamsPanel
                  nodeIds={IMAGE_GEN_PARAM_NODE_IDS}
                  labels={IMAGE_GEN_PARAM_LABELS}
                  selectedNodeId={selectedNodeId}
                  novelId={novelId}
                />
              )}
              {tab === 'sandbox' && (
                <ImageGenNodeParamsPanel
                  nodeIds={SANDBOX_IMAGE_GEN_PARAM_NODE_IDS}
                  labels={SANDBOX_IMAGE_GEN_PARAM_LABELS}
                  configKey="sandbox_llm_params"
                  selectedNodeId={selectedNodeId}
                  novelId={novelId}
                />
              )}
            </div>
          </SidebarInset>
          {tab === 'skeleton' && <PipelineConfigPanel novelId={novelId} onSelectNode={setSelectedNodeId} />}
          {tab === 'sandbox' && <SandboxDialogueTurnCountPanel novelId={novelId} />}
          {tab === 'runtime' && <AuthorLoopConfigPanel novelId={novelId} onSelectNode={setSelectedNodeId} />}
        </div>
      </SidebarProvider>
    </div>
  )
}
