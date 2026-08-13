// Line-driven multi-agent author pipeline view (parallel profile; compare classic AUTHOR_LOOP_STAGES).
export type DialogueStageKind = 'agent-config' | 'mechanism' | 'review'

export interface DialogueStageDef {
  id: string
  label: string
  kind: DialogueStageKind
  /** Shown under the label on 'agent-config'-kind nodes; falls back to a generic
   *  sampling-params hint when omitted (see DialogueDirectorNode.tsx). */
  hint?: string
  /** Which independently-configurable review-hook group this 'review'-kind
   * node reads/writes (buildtime = skeleton-expansion's axis, runtime =
   * author_loop's candidate-prose axis); only meaningful when kind === 'review'. */
  reviewGroup?: 'buildtime' | 'runtime' | 'setup'
  /** Branch node: positioned below its source instead of on the main x-axis chain.
   *  For terminal fire-and-forget side-effects only (no outgoing edge back into
   *  the main flow) -- use `lane` instead for nodes that rejoin downstream. */
  branch?: boolean
  /** True fire-and-forget / non-blocking node -- controls async styling only. */
  async?: boolean
  /** Explicit column (x-rank). Nodes sharing a column render at the same x,
   *  letting parallel tracks fan out from a common source and fan back in
   *  (see runStages.ts). Falls back to sequential array order when omitted. */
  col?: number
  /** Explicit lane (row); 0 = center line (default). Fractional values (e.g. ±0.5)
   *  place a node halfway between lanes for tighter hub-adjacent spacing. */
  lane?: number
  position: { x: number; y: number }
}

export interface DialogueStageEdge {
  source: string
  target: string
  /** Async edge: dashed stroke; does not block the main chain (e.g. derive→guard). */
  async?: boolean
  /** React Flow handle id on the source node (see StageHandles.tsx). */
  sourceHandle?: string
  /** React Flow handle id on the target node (see StageHandles.tsx). */
  targetHandle?: string
}

export const DIALOGUE_STAGE_AXIS_Y = 120
export const DIALOGUE_STAGE_X_STEP = 220

// Matches the real react_graph.py pipeline: task_packet -> author_prose (director)
// -> review_stage -> advance (loops back to the next stage's task_packet). prose_guard/derive/
// guard/summary were leftover labels from the pre-ReAct-refactor architecture (state is read
// live from archive per (chapter, stage), not derived/summarized by a pipeline step) and have
// been removed rather than relabeled -- nothing in the current backend corresponds to them.
export const DIALOGUE_LOOP_STAGES: DialogueStageDef[] = [
  { id: 'director', label: '导演（一次直出定稿正文）', kind: 'agent-config', position: { x: 1 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y } },
  { id: 'review', label: '正文审核', kind: 'review', reviewGroup: 'runtime', position: { x: 2 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y } },
  { id: 'state_derive', label: '角色状态推演', kind: 'mechanism', branch: true, position: { x: 2 * DIALOGUE_STAGE_X_STEP, y: DIALOGUE_STAGE_AXIS_Y } },
]

export const DIALOGUE_STAGE_EDGES: DialogueStageEdge[] = [
  { source: 'director', target: 'review' },
  { source: 'review', target: 'state_derive' },
]
