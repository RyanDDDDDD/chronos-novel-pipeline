import { useEffect, useState } from 'react'
import { Bubble } from '@/shared/components/ui/bubble'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'

type EventLogEntry = { summary: string; time: string; location?: string; characters?: string[] }

/** Event-log entry rendering for keyword-recall archive -- sibling to RollingSummaryBubble.
 * Violet color scheme distinguishes it from sky (rolling summary) / emerald (character) /
 * amber (scene). Defaults closed unless forceOpen is set. Shows all four elements the backend
 * now extracts (event/time/location/characters); location/characters are optional and each
 * degrades to no row when absent. Takes the full entries array for a round/beat and renders a
 * single collapsible trigger -- a round producing several archived events must not stack one
 * "记忆归档" tag per entry. */
export function EventLogBubble({
  entries, forceOpen,
}: {
  entries: EventLogEntry[]
  forceOpen?: boolean
}) {
  // forceOpen re-forces on every change (page-level "expand/collapse all"); once set to a
  // defined value it must remain user-toggleable afterward, or the bubble becomes permanently
  // unclickable (Collapsible only self-manages when uncontrolled).
  const [open, setOpen] = useState(() => forceOpen ?? false)
  useEffect(() => {
    // syncing an external forceOpen prop into local state (getDerivedStateFromProps-style);
    // not a useMemo candidate since it must NOT re-derive from other deps (see comment above).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (forceOpen !== undefined) setOpen(forceOpen)
  }, [forceOpen])

  const nonEmpty = entries.filter((entry) => entry.summary)
  if (nonEmpty.length === 0) return null
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Bubble variant="ghost" className="text-xs">
        <CollapsibleTrigger className="cursor-pointer select-none text-[var(--c-tag-violet-text)] font-medium">
          🕮 记忆归档
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2 space-y-2 border-l-2 border-[var(--c-tag-violet-border)] pl-2">
          {nonEmpty.map((entry, i) => (
            <div key={i} className={`space-y-1 ${i > 0 ? 'pt-2 border-t border-[var(--c-tag-violet-border)]' : ''}`}>
              <div className="text-slate-500">事件：{entry.summary}</div>
              {entry.time && <div className="text-slate-500">时刻：{entry.time}</div>}
              {entry.location && <div className="text-slate-500">地点：{entry.location}</div>}
              {entry.characters && entry.characters.length > 0 && (
                <div className="text-slate-500">人物：{entry.characters.join('、')}</div>
              )}
            </div>
          ))}
        </CollapsibleContent>
      </Bubble>
    </Collapsible>
  )
}
