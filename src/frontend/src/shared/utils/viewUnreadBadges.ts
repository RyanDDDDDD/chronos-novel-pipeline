import type { View } from '@/shared/utils/novelRoute'

export const NOTIFY_VIEWS = ['author', 'chat', 'sandbox', 'archives'] as const
export type NotifyView = (typeof NOTIFY_VIEWS)[number]

export type ViewUnreadState = Record<NotifyView, boolean>

export const EMPTY_VIEW_UNREAD: ViewUnreadState = {
  author: false,
  chat: false,
  sandbox: false,
  archives: false,
}

/** Accepts a plain string so callers can pass either a top-level View or a setup SetupTab
 * value ('archives') -- 'archives' stopped being a View once setup's subtabs became real
 * routes (see novelRoute.ts), but it's still a valid NotifyView badge key. */
export function isNotifyView(v: string): v is NotifyView {
  return (NOTIFY_VIEWS as readonly string[]).includes(v)
}

/** Map a WS event type to the header tab that should show an unread badge.
 * timeline_cascade_done only (not _start/_restarted) -- the archives tab's red dot is meant to mean
 * "a background derivation finished while you were away", not "one is happening". */
export function viewForWsEventType(type: string): NotifyView | null {
  if (type.startsWith('author_loop_')) return 'author'
  if (type.startsWith('setup_chat_')) return 'chat'
  if (type.startsWith('story_sandbox_')) return 'sandbox'
  if (type === 'timeline_cascade_done') return 'archives'
  return null
}

/** Mark unread when an event targets a tab that is not currently active. */
export function markViewUnread(
  prev: ViewUnreadState,
  eventType: string,
  activeView: View,
  isViewingArchives = false,
): ViewUnreadState {
  const target = viewForWsEventType(eventType)
  if (!target || target === activeView) return prev
  if (target === 'archives' && isViewingArchives) return prev
  if (prev[target]) return prev
  return { ...prev, [target]: true }
}

/** Clear unread for a tab when the user navigates to it. */
export function clearViewUnread(prev: ViewUnreadState, view: NotifyView): ViewUnreadState {
  if (!prev[view]) return prev
  return { ...prev, [view]: false }
}
