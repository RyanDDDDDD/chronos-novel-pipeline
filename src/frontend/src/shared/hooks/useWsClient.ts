import { useSelector } from 'react-redux'
import { selectConnected } from '@/shared/store/connectionSlice'
import { getWsInstance } from '@/shared/store/wsMiddleware'

/** Raw WebSocket accessor for the two leaf panels (SetupChatPanel/StorySandboxPanel) that
 * still need to attach their own message listener directly -- not Redux state, just a
 * live-binding read of the single connection wsMiddleware owns. */
export function useWsClient(): WebSocket | null {
  const connected = useSelector(selectConnected)
  return connected ? getWsInstance() : null
}
