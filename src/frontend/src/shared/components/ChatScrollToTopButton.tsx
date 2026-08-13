import { ChevronUp } from 'lucide-react'

/** Shown at the top of the chat viewport when the user has scrolled down. */
export default function ChatScrollToTopButton({
  visible, onClick,
}: { visible: boolean; onClick: () => void }) {
  if (!visible) return null
  return (
    <div className="pointer-events-none absolute inset-x-0 top-3 z-10 flex justify-center">
      <button
        type="button"
        onClick={onClick}
        className="pointer-events-auto chat-scroll-jump-btn inline-flex items-center gap-1 rounded-full border px-3 py-1.5 text-sm font-medium"
      >
        <ChevronUp size={16} aria-hidden />
        跳转至顶部
      </button>
    </div>
  )
}
