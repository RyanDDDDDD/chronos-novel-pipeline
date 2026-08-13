import type { ChatEvent } from '@/shared/utils/setup'

export type ChatMsg = { id: string; role: 'user' | 'assistant' | 'system'; content: string; thinking?: string }

/** Conversation content only (messages/live/status) -- pendingChoice lives exclusively in
 * setupChatSlice's own top-level field (see reduceSetupChatPendingChoice), already fed by the
 * same wsEventReceived dispatch this reducer's caller uses, so it doesn't need a second,
 * redundant copy here. */
export type ChatState = {
  messages: ChatMsg[]
  live: string
  status: string
}

export const EMPTY_CHAT_STATE: ChatState = { messages: [], live: '', status: '' }

/** Completes stable ids for a legacy/REST message shape (no id).*/
export function normalizeChatMessages(
  msgs: (Partial<ChatMsg> & Pick<ChatMsg, 'role' | 'content'>)[],
): ChatMsg[] {
  return msgs.map((m, i) => ({
    id: m.id ?? `legacy-${i}`,
    role: m.role,
    content: m.content,
    ...(m.thinking ? { thinking: m.thinking } : {}),
  }))
}

export function newMsgId(): string {
  return crypto.randomUUID()
}

/** Format selected choice labels for display and outbound user message (one bullet per line). */
export function formatChoiceMessage(labels: string[]): string {
  return labels.map((label) => `• ${label}`).join('\n')
}

/** Merge checkbox selections with optional free-text feedback for present_choices replies. */
export function formatChoiceSubmission(selectedLabels: string[], customText = ''): string {
  const custom = customText.trim()
  const labels = custom ? [...selectedLabels, custom] : selectedLabels
  return formatChoiceMessage(labels)
}

/** All option indices for select-all in a multi-choice card. */
export function allChoiceIndices(optionCount: number): Set<number> {
  return new Set(Array.from({ length: optionCount }, (_, i) => i))
}

// Pure function: fold a WS event into the chat state (can be tested individually, components and
// IO are kept thin). setup_chat_choice is deliberately not handled here -- pendingChoice is owned
// entirely by setupChatSlice's own reducer (see the ChatState docstring above).
export function reduceChatEvent(s: ChatState, ev: ChatEvent): ChatState {
  switch (ev.type) {
    case 'setup_chat_token':
      return { ...s, live: s.live + ev.delta, status: '' }
    case 'setup_chat_tool': {
      if (ev.phase === 'progress') {
        const stepLabel: Record<string, string> = {
          recall: '检索本地研究库…', web: '联网检索…', distill: '蒸馏检索结果…',
        }
        return { ...s, status: ev.label ?? stepLabel[ev.step ?? ''] ?? '检索中…' }
      }
      return s
    }
    case 'setup_chat_final':
      return {
        ...s,
        messages: [...s.messages, {
          id: newMsgId(), role: 'assistant', content: ev.content,
          ...(ev.thinking ? { thinking: ev.thinking } : {}),
        }],
        live: '',
        status: '',
      }
    case 'setup_chat_done':
      return { ...s, live: '', status: '' }
    case 'setup_chat_error':
      return {
        ...s,
        messages: [...s.messages, { id: newMsgId(), role: 'assistant', content: `⚠️ ${ev.error}` }],
        live: '',
        status: '',
      }
    case 'setup_chat_notice':
      return {
        ...s,
        messages: [...s.messages, { id: newMsgId(), role: 'system', content: ev.content }],
      }
    case 'setup_chat_turn_cancelled':
      return { ...s, live: '', status: '' }
    default:
      return s
  }
}
