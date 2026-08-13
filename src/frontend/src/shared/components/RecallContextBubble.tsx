import { useEffect, useState } from 'react'
import ChatMarkdown from '@/shared/components/ChatMarkdown'
import { Bubble } from '@/shared/components/ui/bubble'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'

/** Recall-context rendering: shows what recall_relevant_context(instruction) found for this
 * round -- unlike its siblings (Scene/CharacterState/RollingSummary bubbles), this one always
 * renders something (a placeholder when nothing was recalled) rather than returning null, so
 * users can confirm the mechanism ran even on a miss. Indigo color scheme distinguishes it from
 * the emerald (character) / amber (scene) / sky (rolling summary) siblings. Body uses ChatMarkdown
 * because recall payloads are headed lists (## / -) from the recall composer. */
export function RecallContextBubble({
  recallContext, forceOpen,
}: {
  recallContext: string
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

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Bubble variant="ghost" className="text-xs">
        <CollapsibleTrigger className="cursor-pointer select-none text-indigo-700 font-medium">
          🔍 记忆召回
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2 text-slate-500 border-l-2 border-indigo-200 pl-2">
          {recallContext ? <ChatMarkdown content={recallContext} /> : '（无相关召回）'}
        </CollapsibleContent>
      </Bubble>
    </Collapsible>
  )
}
