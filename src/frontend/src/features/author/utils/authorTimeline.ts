import type { AuthorMessage } from '@/shared/types'

export type AuthorContextGroup = {
  segIndex: number
  anchorIdx: number
  state?: Extract<AuthorMessage, { type: 'state' }>
  event?: Extract<AuthorMessage, { type: 'event_log' }>
  recall?: Extract<AuthorMessage, { type: 'recall' }>
}

export type AuthorTimelineItem =
  | { kind: 'message'; message: AuthorMessage; messageIdx: number }
  | { kind: 'context'; group: AuthorContextGroup }

const CONTEXT_ID_RE = /^seg-(-?\d+)-(state|event_log|recall)$/

/** Segment index encoded in WS/hydrated message ids (`seg-0-state`, etc.). */
export function parseAuthorContextIndex(id: string): number | null {
  const m = CONTEXT_ID_RE.exec(id)
  return m ? Number(m[1]) : null
}

function isContextMessage(m: AuthorMessage): m is Extract<AuthorMessage, { type: 'state' | 'event_log' | 'recall' }> {
  return m.type === 'state' || m.type === 'event_log' || m.type === 'recall'
}

/** Group per-beat recall/state/event_log into one render unit anchored at the last message. */
export function buildAuthorTimelineItems(messages: AuthorMessage[]): AuthorTimelineItem[] {
  const groups = new Map<number, AuthorContextGroup>()

  messages.forEach((m, i) => {
    if (!isContextMessage(m)) return
    const segIndex = parseAuthorContextIndex(m.id)
    if (segIndex === null) return

    let group = groups.get(segIndex)
    if (!group) {
      group = { segIndex, anchorIdx: i }
      groups.set(segIndex, group)
    } else {
      group.anchorIdx = Math.max(group.anchorIdx, i)
    }

    if (m.type === 'state') group.state = m
    else if (m.type === 'event_log') group.event = m
    else group.recall = m
  })

  const anchorToGroup = new Map<number, AuthorContextGroup>()
  for (const group of groups.values()) {
    anchorToGroup.set(group.anchorIdx, group)
  }

  const skipIdx = new Set<number>()
  for (const group of groups.values()) {
    messages.forEach((m, i) => {
      if (!isContextMessage(m)) return
      const segIndex = parseAuthorContextIndex(m.id)
      if (segIndex === group.segIndex && i !== group.anchorIdx) skipIdx.add(i)
    })
  }

  const items: AuthorTimelineItem[] = []
  messages.forEach((m, i) => {
    if (skipIdx.has(i)) return
    const group = anchorToGroup.get(i)
    if (group) {
      items.push({ kind: 'context', group })
      return
    }
    items.push({ kind: 'message', message: m, messageIdx: i })
  })
  return items
}

export function authorContextGroupHasContent(group: AuthorContextGroup): boolean {
  if (group.recall) return true
  if (group.state && group.state.characters.length > 0) return true
  if (group.event?.events.some((e) => e.summary)) return true
  return false
}
