// story_sandbox 真实回合图可视化：dialogue_draft -> prose -> {derive_char, derive_scene,
// summary_fold, event_extract->profile_mutate} -> suggest（四路 fan-in，非 fire-and-forget，无
// async 虚线的实边）。对照 engine/story_sandbox/graph.py 的 _compile_graph 常规轮次拓扑（不含仅
// 开场触发一次的 init_char/init_scene，见该文件模块注释）。identify_cast（仅开场轮）、
// selection_rewrite（导演选中一段正文要求局部重写，完全独立于 run_turn 的按需触发流程）都不是
// 常规轮次拓扑的一部分，用 `async: true` 画成虚线——分别指向 dialogue_draft/prose，表示"条件/
// 按需触发，不是每轮都走"，不是真实的并发边。
// 与 dialogueLoopStages.ts（写作运行时）/skeletonExpansionStages.ts（骨架扩写）平级，同为
// PipelineWorkflowConfigView.tsx 的第三个 tab。
//
// derive_char/derive_scene/summary_fold/event_extract 四条支线都从 prose fan-out 并在 suggest fan-in，
// 用显式 col（x 列）+ lane（并行行）布局：derive_char/derive_scene/summary_fold 各占一条独立的行
// （lane -1/1/2），event_extract->profile_mutate 走中心行（lane 0）；各行共享 prose/suggest
// 两端。derive_char/derive_scene/summary_fold 会 rejoin 主流程（连到 suggest），不是终态副作用，
// 因此不能用 `branch`（那是给不回流主链路的旁支副作用用的，见 dialogueLoopStages.ts）。
import type { DialogueStageDef, DialogueStageEdge } from '@/shared/utils/dialogueLoopStages'
import { DIALOGUE_STAGE_AXIS_Y, DIALOGUE_STAGE_X_STEP } from '@/shared/utils/dialogueLoopStages'

export const SANDBOX_RUN_STAGES: DialogueStageDef[] = [
  { id: 'identify_cast', label: '在场角色识别（仅开场轮）', kind: 'mechanism', col: -2, lane: -2, position: { x: -2 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y } },
  { id: 'dialogue_draft', label: '联合台词草稿', kind: 'mechanism', col: -1, lane: 0, position: { x: -1 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y } },
  { id: 'prose', label: '正文编写', kind: 'mechanism', col: 0, lane: 0, position: { x: 0 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y } },
  { id: 'derive_char', label: '角色状态推演', kind: 'mechanism', col: 1, lane: -1, position: { x: 1 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y } },
  { id: 'event_extract', label: '事件抽取', kind: 'mechanism', col: 1, lane: 0, position: { x: 1 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y } },
  { id: 'derive_scene', label: '场景状态推演', kind: 'mechanism', col: 1, lane: 1, position: { x: 1 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y } },
  { id: 'summary_fold', label: '剧情摘要折叠', kind: 'mechanism', col: 1, lane: 2, position: { x: 1 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y } },
  { id: 'selection_rewrite', label: '选中片段重写（按需触发）', kind: 'mechanism', col: 1, lane: 3, position: { x: 1 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y } },
  { id: 'profile_mutate', label: '角色档案演变', kind: 'mechanism', col: 2, lane: 0, position: { x: 2 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y } },
  { id: 'suggest', label: '剧情选项建议', kind: 'mechanism', col: 3, lane: 0, position: { x: 3 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y } },
]

export const SANDBOX_RUN_EDGES: DialogueStageEdge[] = [
  { source: 'identify_cast', target: 'dialogue_draft', async: true },
  { source: 'dialogue_draft', target: 'prose' },
  { source: 'prose', target: 'derive_char' },
  { source: 'prose', target: 'derive_scene' },
  { source: 'prose', target: 'event_extract' },
  { source: 'prose', target: 'summary_fold' },
  { source: 'prose', target: 'selection_rewrite', async: true },
  { source: 'event_extract', target: 'profile_mutate' },
  { source: 'derive_char', target: 'suggest' },
  { source: 'derive_scene', target: 'suggest' },
  { source: 'profile_mutate', target: 'suggest' },
  { source: 'summary_fold', target: 'suggest' },
]
