/** Infer "processing" lock based on setup_chat WS event (App level, no loss when switching pages).*/
export function reduceSetupChatBusy(busy: boolean, ev: { type: string }): boolean {
  if (ev.type === 'setup_chat_done' || ev.type === 'setup_chat_error' || ev.type === 'setup_chat_turn_cancelled') {
    return false
  }
  if (ev.type === 'setup_chat_queued') return busy
  if (ev.type.startsWith('setup_chat_')) return true
  return busy
}
