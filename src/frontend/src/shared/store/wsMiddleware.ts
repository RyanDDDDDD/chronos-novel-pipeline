import type { Middleware, Dispatch } from '@reduxjs/toolkit'
import { wsConnected, wsDisconnected } from '@/shared/store/connectionSlice'
import { type OrchestratorEvent } from '@/shared/store/wsActions'
import { dispatchInboundWsEvent, WsTokenCoalescer } from '@/shared/store/wsInboundDispatch'

let activeWs: WebSocket | null = null

/** 供不需要经 Redux 的原始 WS 消费方（useWsClient，见 Task 11）读取当前连接。 */
export function getWsInstance(): WebSocket | null {
  return activeWs
}

/** 唯一负责建连/重连/收消息的中间件。当前产品没有任何 ws.send(...)（写操作全走 REST），
 * 所以只处理接收方向；不拦截任何 outbound action。 */
export function createWsMiddleware(): Middleware {
  let reconnectTimeout: ReturnType<typeof setTimeout> | null = null
  const tokenCoalescer = new WsTokenCoalescer()
  // Highest buffered-event `_seq` applied so far. Sent back as `?since_seq=` on (re)connect so
  // the gateway only replays what this tab hasn't already applied, instead of the full buffer
  // on every reconnect (which could otherwise re-apply the same event twice).
  let lastSeq = 0

  function connect(dispatch: Dispatch): void {
    if (activeWs?.readyState === WebSocket.OPEN || activeWs?.readyState === WebSocket.CONNECTING) return

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${proto}//${window.location.host}/ws?since_seq=${lastSeq}`)

    ws.onerror = () => {
      console.error('[WebUI] WebSocket connection failed')
    }
    ws.onopen = () => {
      activeWs = ws
      dispatch(wsConnected())
      console.log('[WebUI] WebSocket connected')
    }
    ws.onclose = () => {
      activeWs = null
      tokenCoalescer.reset()
      dispatch(wsDisconnected())
      console.log('[WebUI] WebSocket disconnected')
      if (reconnectTimeout !== null) clearTimeout(reconnectTimeout)
      reconnectTimeout = setTimeout(() => connect(dispatch), 3000)
    }
    ws.onmessage = (event: MessageEvent) => {
      let data: OrchestratorEvent
      try {
        data = JSON.parse(event.data as string) as OrchestratorEvent
      } catch (e) {
        console.error('[WebUI] Failed to parse WebSocket JSON:', e, event.data)
        return
      }
      if (typeof data._seq === 'number' && data._seq > lastSeq) lastSeq = data._seq
      try {
        dispatchInboundWsEvent(dispatch, data, tokenCoalescer)
      } catch (e) {
        console.error('[WebUI] Failed to apply WebSocket event:', e, event.data)
      }
    }
  }

  return (store) => {
    connect(store.dispatch)
    return (next) => (action) => next(action)
  }
}

export const wsMiddleware = createWsMiddleware()
