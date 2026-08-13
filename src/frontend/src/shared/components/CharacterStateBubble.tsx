import { useEffect, useState } from 'react'
import type { CharacterState, StateDeriveFieldSpec } from '@/shared/types'
import { BASELINE_STATE_DERIVE_FIELDS, formatStateFieldValue } from '@/shared/utils/characterStateFields'
import { Bubble } from '@/shared/components/ui/bubble'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'

/** Shared rendering for dynamic character-state fields in story-sandbox and dialogue_mode --
 * distinct from the static character card (identity/personality/physique/etc., resolved once
 * elsewhere, never re-derived or duplicated here). */
export function CharacterStateBubble({
  characters, entry, title, forceOpen, fields = BASELINE_STATE_DERIVE_FIELDS,
}: {
  characters: CharacterState[]
  entry?: boolean
  title?: string
  /** Overrides the entry-based default when set -- lets a page-level "expand/collapse all"
   * control force every bubble's fold state at once. */
  forceOpen?: boolean
  fields?: StateDeriveFieldSpec[]
}) {
  // Mirrors the original native <details open={forceOpen ?? entry}> exactly: React only
  // resyncs the DOM `open` attribute when the *computed* value actually changes between
  // renders (not on every render), so the user's manual clicks stick in between. A Collapsible
  // that's simply `open={forceOpen ?? entry}` with no onOpenChange doesn't get that "only
  // resync on change" behavior for free -- it's permanently controlled, so clicks would never
  // stick at all. Reproducing the original's actual semantics needs local state seeded by the
  // derived value, re-synced only when that derived value itself changes.
  const derivedOpen = forceOpen ?? entry ?? false
  const [open, setOpen] = useState(derivedOpen)
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- see comment above `derivedOpen`
    setOpen(derivedOpen)
  }, [derivedOpen])

  if (characters.length === 0) return null
  const heading = title ?? (entry ? '🧬 角色进入态（初始）' : '🧬 角色状态（推演）')
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Bubble variant="ghost" className="text-xs">
        <CollapsibleTrigger className="cursor-pointer select-none text-emerald-700 font-medium">
          {heading} · {characters.map(c => c.name).join('、')}
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2 space-y-2">
          {characters.map(c => (
            <div key={c.name} className="border-l-2 border-emerald-200 pl-2">
              <div className="font-semibold text-slate-600">{c.name}</div>
              {fields.map(({ key, label, kind }) => {
                const formatted = formatStateFieldValue(kind, c[key])
                return formatted ? (
                  <div key={key} className="text-slate-500">{label}：{formatted}</div>
                ) : null
              })}
            </div>
          ))}
        </CollapsibleContent>
      </Bubble>
    </Collapsible>
  )
}
