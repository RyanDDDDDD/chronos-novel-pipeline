import { ChevronDown } from 'lucide-react'

/** Shown at the bottom of the chat viewport when the user has scrolled up. */
export default function ChatScrollToBottomButton({
  visible, hasNewContent, onClick,
}: { visible: boolean; hasNewContent?: boolean; onClick: () => void }) {
  if (!visible) return null
  const label = hasNewContent ? '跳转至底部（接收到新消息）' : '跳转至底部'
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-3 z-10 flex justify-center">
      <button
        type="button"
        onClick={onClick}
        className="pointer-events-auto chat-scroll-jump-btn inline-flex items-center gap-1 rounded-full border px-3 py-1.5 text-sm font-medium"
      >
        <ChevronDown size={16} aria-hidden />
        {label}
      </button>
    </div>
  )
}
