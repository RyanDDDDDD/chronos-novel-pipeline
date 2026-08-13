import { describe, it, expect } from 'vitest'
import { reduceSetupChatPendingChoice, derivePendingChoiceFromMessages } from './setupChatPendingChoice'

describe('reduceSetupChatPendingChoice', () => {
  it('sets pending choice on setup_chat_choice', () => {
    const out = reduceSetupChatPendingChoice(null, {
      type: 'setup_chat_choice', question: '选哪个？', options: ['甲', '乙'],
    })
    expect(out).toEqual({ question: '选哪个？', options: ['甲', '乙'] })
  })

  it('ignores malformed setup_chat_choice payloads', () => {
    expect(reduceSetupChatPendingChoice(null, { type: 'setup_chat_choice' })).toBeNull()
    expect(reduceSetupChatPendingChoice(null, { type: 'setup_chat_choice', question: 'q' })).toBeNull()
  })

  it('leaves pending choice untouched on unrelated events', () => {
    const prev = { question: 'q', options: ['x'] }
    expect(reduceSetupChatPendingChoice(prev, { type: 'setup_chat_token' })).toBe(prev)
    expect(reduceSetupChatPendingChoice(prev, { type: 'author_loop_done' })).toBe(prev)
  })
})

describe('derivePendingChoiceFromMessages', () => {
  it('returns null for an empty list', () => {
    expect(derivePendingChoiceFromMessages([])).toBeNull()
  })

  it('returns the choice when it is the last record', () => {
    const msgs = [
      { role: 'user', content: '你好' },
      { role: 'choice', content: '继续吗？', options: ['是', '否'] },
    ]
    expect(derivePendingChoiceFromMessages(msgs)).toEqual({ question: '继续吗？', options: ['是', '否'] })
  })

  it('skips a trailing assistant reply that follows the choice', () => {
    const msgs = [
      { role: 'user', content: '你好' },
      { role: 'choice', content: '继续吗？', options: ['是', '否'] },
      { role: 'assistant', content: '以上是我准备的选项。' },
    ]
    expect(derivePendingChoiceFromMessages(msgs)).toEqual({ question: '继续吗？', options: ['是', '否'] })
  })

  it('returns null once a user record follows the choice (answered)', () => {
    const msgs = [
      { role: 'choice', content: '继续吗？', options: ['是', '否'] },
      { role: 'assistant', content: '以上是我准备的选项。' },
      { role: 'user', content: '是' },
    ]
    expect(derivePendingChoiceFromMessages(msgs)).toBeNull()
  })

  it('defaults options to [] when absent on a choice record', () => {
    const msgs = [{ role: 'choice', content: '继续吗？' }]
    expect(derivePendingChoiceFromMessages(msgs)).toEqual({ question: '继续吗？', options: [] })
  })
})
