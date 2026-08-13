import { useEffect, useState } from 'react'
import { Bubble } from '@/shared/components/ui/bubble'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'

const CATEGORY_LABELS: Record<string, string> = {
  factions: '势力',
  geography: '地理',
  races: '种族',
  power_system: '力量体系',
}

/** Highlights just the world-bible named entries (factions/geography/races/power_system) that
 * recall_relevant_context matched for this round -- a structured subset of RecallContextBubble's
 * flat text, so the user can confirm at a glance whether a specific setting was actually recalled
 * this turn (vs. buried in a mixed event-history block). Unlike RecallContextBubble (which always
 * renders, showing a placeholder on a miss), this returns null on an empty match -- there's
 * nothing useful to say about "no settings recalled" the way there is for the mixed block. */
export function RecalledSettingsBubble({
  recalledSettings, forceOpen,
}: {
  recalledSettings: { category: string; name: string; desc: string }[]
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

  if (recalledSettings.length === 0) return null
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Bubble variant="ghost" className="text-xs">
        <CollapsibleTrigger className="cursor-pointer select-none text-[var(--c-tag-violet-text)] font-medium">
          📚 设定回收 ({recalledSettings.length})
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2 space-y-1 text-slate-600 border-l-2 border-[var(--c-tag-violet-border)] pl-2">
          {recalledSettings.map((s, i) => (
            <p key={i}>
              <span className="text-[var(--c-tag-violet-text)]">[{CATEGORY_LABELS[s.category] ?? s.category}]</span>
              {' '}【{s.name}】{s.desc}
            </p>
          ))}
        </CollapsibleContent>
      </Bubble>
    </Collapsible>
  )
}
