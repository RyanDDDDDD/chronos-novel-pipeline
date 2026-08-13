import { forwardRef, useEffect } from 'react'
import { Send, Square } from 'lucide-react'
import ChatComposerInput from '@/shared/components/ChatComposerInput'
import type { MentionCandidate } from '@/shared/components/mention/mentionCandidates'
import { Button } from '@/shared/components/ui/button'

interface Props {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  onCancel: () => void
  busy: boolean
  cancelling?: boolean
  disabled?: boolean
  placeholder?: string
  onKeyDown?: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void
  bare?: boolean
  /** Opt-in @ 提示候选名单，原样透传给 ChatComposerInput。 */
  mentionCandidates?: MentionCandidate[]
}

/** Shared composer row: textarea + send/cancel button + Escape-to-cancel binding. Pure
 * presentation + key binding -- submit/cancel network calls stay in the owning panel (the two
 * panels hit different stop endpoints), so this component never touches fetch/WS. */
const ChatComposerBar = forwardRef<HTMLTextAreaElement, Props>(function ChatComposerBar(
  { value, onChange, onSubmit, onCancel, busy, cancelling = false, disabled, placeholder, onKeyDown, bare = false, mentionCandidates },
  ref,
) {
  useEffect(() => {
    if (!busy) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onCancel])

  return (
    <div className="flex items-end gap-2">
      <div className="relative min-w-0 flex-1 overflow-visible">
        <ChatComposerInput
          ref={ref}
          bare={bare}
          value={value}
          disabled={disabled}
          onChange={onChange}
          onSubmit={onSubmit}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          mentionCandidates={mentionCandidates}
        />
      </div>
      {busy ? (
        <Button
          type="button"
          variant="destructive"
          size="icon-xs"
          aria-label="中断"
          title="中断（Esc）"
          disabled={cancelling}
          onClick={onCancel}
          className="shadow-sm"
        >
          <Square size={12} aria-hidden />
        </Button>
      ) : (
        <Button
          type="button"
          variant="outline"
          size="icon-xs"
          aria-label="发送"
          title="发送"
          disabled={disabled}
          onClick={onSubmit}
          className="shadow-sm"
        >
          <Send size={12} aria-hidden />
        </Button>
      )}
    </div>
  )
})

export default ChatComposerBar
