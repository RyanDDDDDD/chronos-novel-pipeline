// Setup-chat capability-node model bindings, visualized on the pipeline page's "对话" tab.
// image_recognition covers both per-page vision calls and cross-page consolidation
// (engine/setup_chat/image_batch_consolidator.py, invoked internally for multi-image uploads).
// text_recognition is the shared distillation call (chunk_text/run_distillation_from_chunks).
// prose_style_extraction consumes the same imported novel chunks (read_attachment /
// build_prose_style_from_import). image_recognition and character_portrait fan into the
// image_hub grouping node (col 0.5, purely visual — no backend call of its own), which
// then feeds chat_identity; auto_build_setup forks right to chat (col 1) and left to
// timeline_derive / setup_quality_review / incremental_relationship (设定建设链, col -1)
// — three sides of the same entry node; text_recognition sits right of chat (col 2),
// feeding chat leftward and chaining forward to prose_style_extraction (col 3, same lane).
// chat_identity id kept for backend/config continuity; label "对话agent".
// character_portrait: 立绘生成能力标注节点，仅可视化，不接入 NodeLlmParamsPanel（生图不是
// LLM 采样调用）；配置入口是常驻的 PipelineConfigPanel「人物立绘生成」Section，不依赖点击此节点。
// image_hub: "图片" grouping node, purely visual (not in any SELECTABLE_NODE_IDS list, no
// param panel) — collects image_recognition + character_portrait before chat_identity.
// Distinct from dialogueLoopStages.ts (author_loop writing runtime).
//
// Layout: chat lane 0; hub rows at ±HUB_NEAR with downstream chains on the same lane;
// setup fan keeps ±0.5 spacing relative to auto_build (0, 0.5, 1); image group (image_recognition
// + character_portrait) sits at col 0 lanes -1/-0.5, image_hub bridges at col 0.5 lane -HUB_NEAR.
import type { DialogueStageDef, DialogueStageEdge } from '@/shared/utils/dialogueLoopStages'
import { DIALOGUE_STAGE_AXIS_Y, DIALOGUE_STAGE_X_STEP } from '@/shared/utils/dialogueLoopStages'

/** Half lane offset — sits closer to chat (lane 0) than a full ±1 step. */
const HUB_NEAR = 0.5

export const SKELETON_EXPANSION_STAGES: DialogueStageDef[] = [
  {
    id: 'timeline_derive', label: '角色档案自动推演', kind: 'mechanism',
    col: -1, lane: 0,
    position: { x: -1 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y },
  },
  {
    id: 'setup_quality_review', label: '设定质量审查', kind: 'review', reviewGroup: 'setup',
    col: -1, lane: HUB_NEAR,
    position: { x: -1 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y },
  },
  {
    id: 'incremental_relationship', label: '关系推断', kind: 'mechanism',
    col: -1, lane: 1,
    position: { x: -1 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y },
  },
  { id: 'image_recognition', label: '图片识别', kind: 'mechanism', col: 0, lane: -HUB_NEAR, position: { x: 0 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y } },
  {
    id: 'character_portrait', label: '立绘生成', kind: 'mechanism',
    col: 0, lane: -1,
    position: { x: 0 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y },
  },
  { id: 'auto_build_setup', label: '一键建设定', kind: 'mechanism', col: 0, lane: HUB_NEAR, position: { x: 0 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y } },
  {
    id: 'image_hub', label: '图片', kind: 'mechanism',
    col: 0.5, lane: -HUB_NEAR,
    position: { x: 0.5 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y },
  },
  {
    id: 'chat_identity', label: '对话agent', kind: 'agent-config',
    hint: '点击节点配置身份设定', col: 1, lane: 0,
    position: { x: 1 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y },
  },
  {
    id: 'text_recognition', label: '文本识别', kind: 'mechanism',
    col: 2, lane: -HUB_NEAR,
    position: { x: 2 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y },
  },
  {
    id: 'prose_style_extraction', label: '文风抽取', kind: 'mechanism',
    col: 3, lane: -HUB_NEAR,
    position: { x: 3 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y },
  },
  {
    id: 'skeleton_writer', label: '分拍底稿生成', kind: 'mechanism',
    col: 2, lane: HUB_NEAR,
    position: { x: 2 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y },
  },
  {
    id: 'beat_dialogue_draft', label: '拍台词草稿', kind: 'mechanism',
    col: 3, lane: HUB_NEAR,
    position: { x: 3 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y },
  },
  {
    id: 'review', label: '文风/过渡审查', kind: 'review', reviewGroup: 'buildtime',
    col: 4, lane: HUB_NEAR,
    position: { x: 4 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y },
  },
]

export const SKELETON_EXPANSION_EDGES: DialogueStageEdge[] = [
  { source: 'image_recognition', target: 'image_hub' },
  { source: 'character_portrait', target: 'image_hub' },
  { source: 'image_hub', target: 'chat_identity' },
  { source: 'auto_build_setup', target: 'chat_identity' },
  { source: 'auto_build_setup', target: 'timeline_derive', sourceHandle: 'source-left', targetHandle: 'target-right' },
  { source: 'auto_build_setup', target: 'setup_quality_review', sourceHandle: 'source-left', targetHandle: 'target-right' },
  { source: 'auto_build_setup', target: 'incremental_relationship', sourceHandle: 'source-left', targetHandle: 'target-right' },
  { source: 'text_recognition', target: 'chat_identity', sourceHandle: 'source-left', targetHandle: 'target-right' },
  { source: 'text_recognition', target: 'prose_style_extraction' },
  { source: 'chat_identity', target: 'skeleton_writer' },
  { source: 'skeleton_writer', target: 'beat_dialogue_draft' },
  { source: 'beat_dialogue_draft', target: 'review' },
]
