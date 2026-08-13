import type { Dispatch } from '@reduxjs/toolkit'
import { wsEventReceived, type OrchestratorEvent } from '@/shared/store/wsActions'

/** Buffers high-frequency sandbox prose token frames before they hit Redux. */
export class WsTokenCoalescer {
  private sandboxDelta = ''
  private rewriteDelta = ''
  private scheduled = false

  reset(): void {
    this.sandboxDelta = ''
    this.rewriteDelta = ''
    this.scheduled = false
  }

  private flush(dispatch: Dispatch): void {
    if (this.sandboxDelta) {
      const delta = this.sandboxDelta
      this.sandboxDelta = ''
      dispatch(wsEventReceived({ type: 'story_sandbox_token', delta }))
    }
    if (this.rewriteDelta) {
      const delta = this.rewriteDelta
      this.rewriteDelta = ''
      dispatch(wsEventReceived({ type: 'story_sandbox_rewrite_token', delta }))
    }
  }

  private scheduleFlush(dispatch: Dispatch): void {
    if (this.scheduled) return
    this.scheduled = true
    setTimeout(() => {
      this.scheduled = false
      this.flush(dispatch)
    }, 0)
  }

  /** Returns true when the frame was fully handled (no further dispatch needed). */
  apply(dispatch: Dispatch, data: OrchestratorEvent): boolean {
    if (data.type === 'story_sandbox_token' && data.delta) {
      this.sandboxDelta += data.delta
      this.scheduleFlush(dispatch)
      return true
    }
    if (data.type === 'story_sandbox_rewrite_token' && data.delta) {
      this.rewriteDelta += data.delta
      this.scheduleFlush(dispatch)
      return true
    }
    if (data.type.startsWith('story_sandbox_')) {
      this.flush(dispatch)
    }
    return false
  }
}

export function dispatchInboundWsEvent(
  dispatch: Dispatch, data: OrchestratorEvent, coalescer: WsTokenCoalescer,
): void {
  if (!coalescer.apply(dispatch, data)) {
    dispatch(wsEventReceived(data))
  }
}
