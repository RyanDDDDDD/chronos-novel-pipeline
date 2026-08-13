import { describe, it, expect } from 'vitest'
import {
  authorContextGroupHasContent,
  buildAuthorTimelineItems,
  parseAuthorContextIndex,
} from '@/features/author/utils/authorTimeline'
import type { AuthorMessage } from '@/shared/types'

describe('parseAuthorContextIndex', () => {
  it('parses seg-N-context suffix ids', () => {
    expect(parseAuthorContextIndex('seg-0-state')).toBe(0)
    expect(parseAuthorContextIndex('seg-2-event_log')).toBe(2)
    expect(parseAuthorContextIndex('seg--1-recall')).toBe(-1)
  })

  it('returns null for non-context ids', () => {
    expect(parseAuthorContextIndex('seg-0-summary')).toBeNull()
    expect(parseAuthorContextIndex('el0')).toBeNull()
  })
})

describe('buildAuthorTimelineItems', () => {
  const recall: AuthorMessage = {
    id: 'seg-0-recall', role: 'agent', type: 'recall', recallContext: '召回',
  }
  const state: AuthorMessage = {
    id: 'seg-0-state', role: 'agent', type: 'state',
    characters: [{ name: '甲', psychology: '紧张' }],
  }
  const event: AuthorMessage = {
    id: 'seg-0-event_log', role: 'agent', type: 'event_log',
    events: [{ summary: '归档', time: '之后' }],
  }
  const segment: AuthorMessage = {
    id: 'seg-0-beat-0', role: 'agent', type: 'segment',
    segment: { index: 0, intent: '', skill: null, text: '正文', agent: 'synthesis' },
  }

  it('merges same-beat context messages into one item at the last position', () => {
    const messages = [recall, segment, state, event]
    const items = buildAuthorTimelineItems(messages)
    expect(items).toHaveLength(2)
    expect(items[0]).toMatchObject({ kind: 'message', message: segment })
    expect(items[1]).toMatchObject({
      kind: 'context',
      group: {
        segIndex: 0,
        anchorIdx: 3,
        state,
        event,
        recall,
      },
    })
  })

  it('keeps legacy ids as separate message items', () => {
    const legacy: AuthorMessage = {
      id: 'el0', role: 'agent', type: 'event_log',
      events: [{ summary: 'x', time: '' }],
    }
    const items = buildAuthorTimelineItems([legacy])
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ kind: 'message', message: legacy })
  })
})

describe('authorContextGroupHasContent', () => {
  it('true when any subsection has content', () => {
    expect(authorContextGroupHasContent({
      segIndex: 0,
      anchorIdx: 0,
      recall: { id: 'seg-0-recall', role: 'agent', type: 'recall', recallContext: '' },
    })).toBe(true)
    expect(authorContextGroupHasContent({
      segIndex: 0,
      anchorIdx: 0,
      state: { id: 'seg-0-state', role: 'agent', type: 'state', characters: [{ name: '甲' }] },
    })).toBe(true)
  })

  it('false when group is empty', () => {
    expect(authorContextGroupHasContent({ segIndex: 0, anchorIdx: 0 })).toBe(false)
  })
})
