import { FilterMenu } from '@/shared/components/mention/FilterMenu'
import type { MentionCandidate } from './mentionCandidates'

const TYPE_LABELS: Record<MentionCandidate['type'], string> = {
  character: '角色',
  setting: '设定',
}

export default function MentionDropdown({
  candidates,
  selectedIndex,
  onSelect,
  onDismiss,
}: {
  candidates: MentionCandidate[]
  selectedIndex: number
  onSelect: (name: string) => void
  /** Popover closed itself (e.g. Radix's own Escape/outside-interaction handling) without an
   * explicit item pick — close the dropdown only, don't touch the composer's text. Using
   * onSelect('') here used to insert an empty mention and wipe the typed "@query". */
  onDismiss: () => void
}) {
  if (candidates.length === 0) return null
  return (
    <FilterMenu
      open
      side="top"
      anchor={<div className="pointer-events-none absolute inset-x-0 bottom-0" aria-hidden />}
      items={candidates.map((c) => ({
        id: c.name,
        label: c.name,
        sublabel: TYPE_LABELS[c.type],
      }))}
      highlightedId={candidates[selectedIndex]?.name}
      onSelect={onSelect}
      onOpenChange={(next) => { if (!next) onDismiss() }}
    />
  )
}
