import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import {
  applyMentionSelection, filterMentionCandidates, findMentionQuery,
  type MentionCandidate, type MentionQuery,
} from '@/shared/components/mention/mentionCandidates'
import MentionDropdown from '@/shared/components/mention/MentionDropdown'
import { Textarea } from '@/shared/components/ui/textarea'

const INPUT_MIN_PX = 40
const INPUT_MAX_PX = 192

/** Grow textarea height with content; pure DOM helper for tests and callers. */
export function resizeTextareaToFit(
  el: HTMLTextAreaElement,
  minPx = INPUT_MIN_PX,
  maxPx = INPUT_MAX_PX,
): void {
  el.style.height = 'auto'
  const full = el.scrollHeight
  const h = Math.min(Math.max(full, minPx), maxPx)
  el.style.height = `${h}px`
  el.style.overflowY = full > maxPx ? 'auto' : 'hidden'
}

interface Props {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  disabled?: boolean
  placeholder?: string
  onKeyDown?: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void
  /** When true, omit border/bg/rounded/shadow so a parent shell can own chrome. */
  bare?: boolean
  /** Opt-in @ 提示候选名单；未传或空数组时行为与改动前完全一致（其它调用点不受影响）。 */
  mentionCandidates?: MentionCandidate[]
}

const BASE_CLASS =
  'w-full px-2 py-1.5 text-sm placeholder:text-[11px] placeholder:leading-snug placeholder:text-slate-400 resize-none overflow-hidden min-h-[2.5rem] focus:outline-none disabled:text-slate-400 disabled:cursor-not-allowed'
const CHROME_CLASS =
  'rounded-md border border-slate-300 bg-white shadow-sm disabled:bg-slate-100'
const BARE_OVERRIDE_CLASS =
  'border-0 border-none shadow-none rounded-none bg-transparent focus-visible:ring-0 focus-visible:border-transparent aria-invalid:border-transparent'

/** Shared chat composer textarea: auto-resize, Enter to submit, Shift+Enter newline, optional
 * @ mention autocomplete. Forwards a ref to the underlying textarea so a parent can imperatively
 * focus it (e.g. the sandbox panel focuses this after a direction-pill click so Enter sends
 * right away). */
const ChatComposerInput = forwardRef<HTMLTextAreaElement, Props>(function ChatComposerInput(
  { value, onChange, onSubmit, disabled, placeholder, onKeyDown, bare = false, mentionCandidates },
  ref,
) {
  const inputRef = useRef<HTMLTextAreaElement>(null)
  useImperativeHandle(ref, () => inputRef.current as HTMLTextAreaElement)

  const [mention, setMention] = useState<{ query: MentionQuery; selectedIndex: number } | null>(null)
  // 记住被 Escape 关闭的 mention 片段起始位置，直到光标真的移出该片段前不重新弹出；
  // 片段消失（recompute 收到 null）或换到别的片段时自然作废，不用手动清空。
  const dismissedStartRef = useRef<number | null>(null)
  const pendingCursorRef = useRef<number | null>(null)

  useEffect(() => {
    const el = inputRef.current
    if (el) resizeTextareaToFit(el)
    if (pendingCursorRef.current !== null) {
      const pos = pendingCursorRef.current
      pendingCursorRef.current = null
      inputRef.current?.setSelectionRange(pos, pos)
    }
  }, [value])

  const recomputeMention = (text: string, cursor: number) => {
    if (!mentionCandidates || mentionCandidates.length === 0) {
      setMention(null)
      return
    }
    const q = findMentionQuery(text, cursor)
    if (!q) {
      dismissedStartRef.current = null
      setMention(null)
      return
    }
    if (q.start === dismissedStartRef.current) {
      setMention(null)
      return
    }
    setMention({ query: q, selectedIndex: 0 })
  }

  const selectMention = (name: string) => {
    if (!mention) return
    const { start, end } = mention.query
    const result = applyMentionSelection(value, start, end, name)
    pendingCursorRef.current = result.cursor
    dismissedStartRef.current = null
    setMention(null)
    onChange(result.value)
  }

  const dismissMention = () => {
    if (!mention) return
    dismissedStartRef.current = mention.query.start
    setMention(null)
  }

  const candidates = mention
    ? filterMentionCandidates(mentionCandidates ?? [], mention.query.query)
    : []

  return (
    <div className="relative">
      <Textarea
        ref={inputRef}
        className={bare ? `${BASE_CLASS} ${BARE_OVERRIDE_CLASS}` : `${BASE_CLASS} ${CHROME_CLASS}`}
        rows={1}
        value={value}
        disabled={disabled}
        onChange={(e) => {
          const text = e.target.value
          onChange(text)
          recomputeMention(text, e.target.selectionStart ?? text.length)
        }}
        onSelect={(e) => {
          const el = e.currentTarget
          recomputeMention(el.value, el.selectionStart ?? el.value.length)
        }}
        onBlur={() => {
          window.setTimeout(() => setMention(null), 0)
        }}
        onKeyDown={(e) => {
          if (mention) {
            if (candidates.length > 0) {
              if (e.key === 'ArrowDown') {
                e.preventDefault()
                setMention((s) => (s ? { ...s, selectedIndex: (s.selectedIndex + 1) % candidates.length } : s))
                return
              }
              if (e.key === 'ArrowUp') {
                e.preventDefault()
                setMention((s) => (
                  s ? { ...s, selectedIndex: (s.selectedIndex - 1 + candidates.length) % candidates.length } : s
                ))
                return
              }
              if (e.key === 'Enter' || e.key === 'Tab') {
                e.preventDefault()
                selectMention(candidates[mention.selectedIndex].name)
                return
              }
            }
            if (e.key === 'Escape') {
              e.preventDefault()
              dismissMention()
              return
            }
          }
          onKeyDown?.(e)
          if (e.defaultPrevented) return
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            onSubmit()
          }
        }}
        placeholder={placeholder}
      />
      {mention && (
        <MentionDropdown
          candidates={candidates}
          selectedIndex={mention.selectedIndex}
          onSelect={selectMention}
          onDismiss={dismissMention}
        />
      )}
    </div>
  )
})

export default ChatComposerInput
