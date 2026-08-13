import { describe, it, expect } from 'vitest'
import { reduceChatEvent, EMPTY_CHAT_STATE, formatChoiceMessage, formatChoiceSubmission } from './setupChatState'

describe('formatChoiceSubmission', () => {
  it('merges selected labels with optional custom text as bullets', () => {
    expect(formatChoiceSubmission(['甲', '乙'], '我有别的想法')).toBe('• 甲\n• 乙\n• 我有别的想法')
  })

  it('allows custom text only without checkbox selections', () => {
    expect(formatChoiceSubmission([], '只要这个')).toBe('• 只要这个')
  })

  it('preserves checkbox-only replies', () => {
    expect(formatChoiceSubmission(['甲'], '')).toBe(formatChoiceMessage(['甲']))
  })
})

describe('reduceChatEvent', () => {
  it('sets status from label when a progress-phase tool event carries one', () => {
    const out = reduceChatEvent(EMPTY_CHAT_STATE, {
      type: 'setup_chat_tool', name: 'auto_build_setup', phase: 'progress',
      label: '角色 3/8：已建「甲」',
    })
    expect(out.status).toBe('角色 3/8：已建「甲」')
  })

  it('falls back to the step lookup table when label is absent', () => {
    const out = reduceChatEvent(EMPTY_CHAT_STATE, {
      type: 'setup_chat_tool', name: 'recall_research', phase: 'progress', step: 'recall',
    })
    expect(out.status).toBe('检索本地研究库…')
  })

  it('falls back to a generic label when neither label nor a known step is given', () => {
    const out = reduceChatEvent(EMPTY_CHAT_STATE, {
      type: 'setup_chat_tool', name: 'x', phase: 'progress',
    })
    expect(out.status).toBe('检索中…')
  })

  it('does not touch status on start/end phase tool events', () => {
    const withStatus = { ...EMPTY_CHAT_STATE, status: '之前的状态' }
    const out = reduceChatEvent(withStatus, {
      type: 'setup_chat_tool', name: 'x', phase: 'start',
    })
    expect(out.status).toBe('之前的状态')
  })
})
