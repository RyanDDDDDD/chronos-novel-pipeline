import { useRef } from 'react'

/** Terminal-style ↑/↓ history navigation for a composer textarea. `entries` is the ordered
 * (oldest→newest) list of previously submitted texts -- callers derive this from whatever
 * already-persisted state they have (Redux rounds/messages), this hook holds no storage of its
 * own. Only reacts to ArrowUp/ArrowDown at the logical top/bottom line of the current value (no
 * `\n` before/after the caret); any other key or a mid-text caret is left untouched so normal
 * caret movement and other onKeyDown consumers (mention dropdown, slash menu) keep working. */
export function useComposerHistory(entries: string[]) {
  const indexRef = useRef<number | null>(null)
  const draftRef = useRef('')
  const lastSetRef = useRef<string | null>(null)
  const entriesRef = useRef(entries)
  if (entriesRef.current !== entries) {
    entriesRef.current = entries
    indexRef.current = null
  }

  function handleKey(
    e: React.KeyboardEvent<HTMLTextAreaElement>,
    value: string,
    onChange: (v: string) => void,
  ): boolean {
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return false
    // A manual edit since the hook last wrote `value` means the user stepped out of navigation
    // (e.g. tweaked a loaded history line) -- drop back to draft mode before deciding this press.
    if (indexRef.current !== null && value !== lastSetRef.current) {
      indexRef.current = null
    }
    const pos = e.currentTarget.selectionStart ?? 0
    const endPos = e.currentTarget.selectionEnd ?? pos

    if (e.key === 'ArrowUp') {
      if (value.slice(0, pos).includes('\n')) return false
      if (entries.length === 0) return false
      e.preventDefault()
      if (indexRef.current === null) {
        draftRef.current = value
        indexRef.current = entries.length - 1
      } else if (indexRef.current > 0) {
        indexRef.current -= 1
      }
      const next = entries[indexRef.current]
      lastSetRef.current = next
      onChange(next)
      return true
    }

    if (value.slice(endPos).includes('\n')) return false
    if (indexRef.current === null) return false
    e.preventDefault()
    if (indexRef.current < entries.length - 1) {
      indexRef.current += 1
      const next = entries[indexRef.current]
      lastSetRef.current = next
      onChange(next)
    } else {
      indexRef.current = null
      lastSetRef.current = draftRef.current
      onChange(draftRef.current)
    }
    return true
  }

  return { handleKey }
}
