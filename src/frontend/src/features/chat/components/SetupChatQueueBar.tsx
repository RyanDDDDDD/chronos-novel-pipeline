import { Clock, Paperclip, X } from 'lucide-react'
import type { SetupChatQueuedMessage } from '@/features/chat/store/setupChatSlice'
import { Button } from '@/shared/components/ui/button'

type Props = {
  items: SetupChatQueuedMessage[]
  onRemove: (id: string) => void
}

/** Pending user turns held locally until the in-flight agent turn finishes. */
export default function SetupChatQueueBar({ items, onRemove }: Props) {
  if (items.length === 0) return null

  return (
    <div
      data-testid="setup-chat-queue-bar"
      className="pointer-events-auto absolute bottom-full left-4 right-4 z-20 mb-1 overflow-hidden rounded-lg border border-[var(--c-border)] bg-[var(--c-surface)] shadow-float sm:left-6 sm:right-6"
    >
      <div className="flex items-center gap-1.5 border-b border-[var(--c-border)] bg-[var(--c-surface-muted)] px-3 py-1.5 text-xs font-medium text-[var(--c-text-muted)]">
        <Clock size={12} aria-hidden />
        待发送 ({items.length})
      </div>
      <ol data-testid="setup-chat-queue-list" className="max-h-36 space-y-1 overflow-y-auto px-2 py-1.5">
        {items.map((item, index) => (
          <li
            key={item.id}
            className="flex items-start gap-2 rounded-md border border-[var(--c-border)] bg-[var(--c-surface-muted)] px-2 py-1.5"
          >
            <span
              className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-md bg-[var(--c-accent-subtle)] text-[10px] font-medium tabular-nums text-[var(--c-accent)]"
              aria-hidden
            >
              {index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-[var(--c-text-secondary)]">{item.text}</p>
              {item.attachmentIds.length > 0 && (
                <p className="mt-0.5 flex items-center gap-1 text-[11px] text-[var(--c-text-muted)]">
                  <Paperclip size={10} aria-hidden />
                  {item.attachmentIds.length} 个附件
                </p>
              )}
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              className="shrink-0 text-[var(--c-text-muted)] hover:text-red-600"
              aria-label={`移出队列：${item.text}`}
              title="移出队列"
              onClick={() => onRemove(item.id)}
            >
              <X size={10} aria-hidden />
            </Button>
          </li>
        ))}
      </ol>
    </div>
  )
}
