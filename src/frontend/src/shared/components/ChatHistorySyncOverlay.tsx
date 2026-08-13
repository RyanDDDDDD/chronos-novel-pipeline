export const CHAT_HISTORY_SYNC_LABEL = '正在同步对话记录…'

/** Full-panel overlay while chat history is loading from the backend (setup-chat + sandbox). */
export default function ChatHistorySyncOverlay() {
  return (
    <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 bg-white/80">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-violet-600" />
      <p className="text-xs text-slate-500">{CHAT_HISTORY_SYNC_LABEL}</p>
    </div>
  )
}
