export type PendingChoice = { question: string; options: string[] } | null

/** Track the latest setup_chat present_choices question (App level, survives route
 * switching — SetupChatPanel unmounts on navigation but the backend keeps waiting). */
export function reduceSetupChatPendingChoice(
  prev: PendingChoice,
  ev: { type: string; question?: string; options?: string[] },
): PendingChoice {
  if (ev.type === 'setup_chat_choice' && typeof ev.question === 'string' && Array.isArray(ev.options)) {
    return { question: ev.question, options: ev.options }
  }
  return prev
}

/** Derive the still-open present_choices question from the persisted message table -- scans
 * from the tail: a 'user' record means it's already been answered (no pending choice); a
 * 'choice' record found before any 'user' record means it's still open; assistant/system
 * records are skipped over since present_choices is typically followed by a closing assistant
 * reply that lands after the choice record but doesn't resolve it. */
export function derivePendingChoiceFromMessages(
  msgs: { role: string; content: string; options?: string[] }[],
): PendingChoice {
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i]
    if (m.role === 'user') return null
    if (m.role === 'choice') return { question: m.content, options: m.options ?? [] }
  }
  return null
}
