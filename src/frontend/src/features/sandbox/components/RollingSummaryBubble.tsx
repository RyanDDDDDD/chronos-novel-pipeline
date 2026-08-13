import { useEffect, useState } from 'react'
import { Bubble } from '@/shared/components/ui/bubble'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'

/** Rolling-summary rendering, sibling to CharacterStateBubble/SceneStateBubble -- single string
 * field, no per-character grouping. Sky color scheme distinguishes it from the emerald
 * (character) / amber (scene) siblings. Defaults closed (no "entry" concept to default-open on,
 * unlike SceneStateBubble) unless forceOpen is set. */
export function RollingSummaryBubble({
  summary, forceOpen,
}: {
  summary: string
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

  if (!summary) return null
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Bubble variant="ghost" className="text-xs">
        <CollapsibleTrigger className="cursor-pointer select-none text-sky-700 font-medium">
          📜 剧情摘要（滚动）
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2 text-slate-500 border-l-2 border-sky-200 pl-2">
          {summary}
        </CollapsibleContent>
      </Bubble>
    </Collapsible>
  )
}
