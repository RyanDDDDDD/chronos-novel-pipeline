import { createAction } from '@reduxjs/toolkit'

export interface OrchestratorEvent {
  type: string
  /** Monotonic per-process buffer sequence stamped by the gateway on non-transient events;
   * absent on streaming/transient events that never enter the replay buffer. */
  _seq?: number
  novel_id?: string
  reason?: string
  pipeline_id?: string
  chapter?: number
  resume?: boolean
  step?: number
  agent?: string
  attempt?: number
  attempts?: number
  mode?: string
  local?: boolean
  phase?: string
  output_path?: string
  preview?: string
  input?: number
  output?: number
  cached?: number
  content?: string
  delta?: string
  characters?: unknown[]
  entry?: boolean
  event?: { summary: string; time: string; location?: string; characters?: string[] }
  entries?: { summary: string; time: string; location?: string; characters?: string[] }[]
  mutation?: Record<string, Record<string, unknown>> | null
  recall_context?: string
  total?: number
  done?: number
  index?: number
  intent?: string
  psychology?: string
  skill?: string | null
  beat?: number
  beats?: number
  text?: string
  draft?: boolean
  role?: string
  title?: string
  token?: string
  message?: string
  error?: string
  ok?: boolean
  fatal?: boolean
  character?: string
  portrait_path?: string
  chapters?: number[]
  built?: number[]
  subsystem?: string
  key?: string
  tokens_in?: number
  tokens_out?: number
  tokens_cached?: number
  question?: string
  options?: string[]
  depth?: number
}

/** 唯一的入站 WS 事件 action：wsMiddleware 收到消息后统一 dispatch 这一个 action，
 * 各域 slice 各自用 addCase(wsEventReceived, ...) 按 payload.type 认领自己关心的事件。 */
export const wsEventReceived = createAction<OrchestratorEvent>('ws/eventReceived')
