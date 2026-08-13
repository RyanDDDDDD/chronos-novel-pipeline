import { useEffect, useState } from 'react'
import { Bubble } from '@/shared/components/ui/bubble'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'

const SCENE_FIELDS: [key: string, label: string][] = [
  ['description', '环境'],
  ['objects', '物件'],
  ['atmosphere', '氛围'],
  ['disruption', '异常'],
]

/** Scene-state rendering, sibling to CharacterStateBubble -- single object, no per-character
 * grouping needed since there's only one scene. Amber color scheme distinguishes it visually
 * from CharacterStateBubble's emerald. */
export function SceneStateBubble({
  scene, entry, title, forceOpen,
}: {
  scene: Record<string, unknown>
  entry?: boolean
  title?: string
  /** Overrides the entry-based default when set -- lets a page-level "expand/collapse all"
   * control force every bubble's fold state at once. */
  forceOpen?: boolean
}) {
  // Mirrors the original native <details open={forceOpen ?? entry}> exactly: React only
  // resyncs the DOM `open` attribute when the *computed* value actually changes between
  // renders (not on every render), so the user's manual clicks stick in between. Reproducing
  // that with Radix Collapsible needs local state seeded by the derived value, re-synced only
  // when that derived value itself changes -- a plain `open={forceOpen ?? entry}` with no
  // onOpenChange would instead be permanently controlled, blocking clicks entirely.
  const derivedOpen = forceOpen ?? entry ?? false
  const [open, setOpen] = useState(derivedOpen)
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- see comment above `derivedOpen`
    setOpen(derivedOpen)
  }, [derivedOpen])

  const fields = SCENE_FIELDS.filter(([key]) => typeof scene[key] === 'string' && scene[key])
  if (fields.length === 0) return null
  const heading = title ?? (entry ? '🏛️ 场景进入态（初始）' : '🏛️ 场景状态（推演）')
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Bubble variant="ghost" className="text-xs">
        <CollapsibleTrigger className="cursor-pointer select-none text-amber-700 font-medium">
          {heading}
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2 space-y-1 border-l-2 border-amber-200 pl-2">
          {fields.map(([key, label]) => (
            <div key={key} className="text-slate-500">{label}：{scene[key] as string}</div>
          ))}
        </CollapsibleContent>
      </Bubble>
    </Collapsible>
  )
}
