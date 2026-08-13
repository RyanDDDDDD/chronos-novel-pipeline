import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import {
  characterProfileFieldLabel,
  formatProfileScalarDisplay,
} from '@/shared/utils/characterFieldLabels'
import { Bubble } from '@/shared/components/ui/bubble'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'
import type { RelationshipEdge } from '@/shared/types'

type SliderValue = { level: number; text: string }

function isSliderValue(v: unknown): v is SliderValue {
  return typeof v === 'object' && v !== null && 'text' in v
}

function renderProfileFields(fields: Record<string, unknown>) {
  return Object.entries(fields).map(([key, value]) => {
    if (key === 'hobbies' && Array.isArray(value)) {
      return (
        <div key={key} className="text-[var(--c-text-muted)]">
          {characterProfileFieldLabel(key)}：{value.join('、')}
        </div>
      )
    }
    if (key === 'sliders' && typeof value === 'object' && value !== null) {
      return Object.entries(value as Record<string, unknown>).map(([axis, axisVal]) => (
        isSliderValue(axisVal) && (
          <div key={`sliders-${axis}`} className="text-[var(--c-text-muted)]">{axis}：{axisVal.text}</div>
        )
      ))
    }
    if (key === 'physique' && typeof value === 'object' && value !== null) {
      return Object.entries(value as Record<string, unknown>).map(([slot, desc]) => (
        <div key={`physique-${slot}`} className="text-[var(--c-text-muted)]">{slot}：{String(desc)}</div>
      ))
    }
    return (
      <div key={key} className="text-[var(--c-text-muted)]">
        {characterProfileFieldLabel(key)}：{formatProfileScalarDisplay(key, value)}
      </div>
    )
  })
}

function renderRelationshipEdges(edges: Record<string, RelationshipEdge>) {
  return Object.entries(edges).map(([key, edge]) => {
    const terms = [...(edge.from_ref_terms ?? []), ...(edge.to_ref_terms ?? [])]
    return (
      <div key={key} className="text-[var(--c-text-muted)]">
        {edge.from} → {edge.to}（{edge.nature}）
        {edge.relationship_anchor ? ` · ${edge.relationship_anchor}` : ''}
        {terms.length > 0 ? ` · ${terms.join('/')}` : ''}
      </div>
    )
  })
}

/** Profile/relationship-mutation rendering, sibling to EventLogBubble/RollingSummaryBubble --
 * only ever rendered when this turn actually produced a mutation (no empty-state placeholder).
 * Defaults open (unlike the other bubbles' default-closed posture) -- this is a rare,
 * high-signal event worth surfacing immediately. */
export function ProfileMutationBubble({
  mutation, relationshipMutation, forceOpen,
  onRewrite, rewriting,
}: {
  mutation?: Record<string, Record<string, unknown>> | null
  relationshipMutation?: Record<string, RelationshipEdge> | null
  forceOpen?: boolean
  onRewrite?: (feedback: string) => void
  rewriting?: boolean
}) {
  const profileNames = Object.keys(mutation ?? {})
  const relationshipKeys = Object.keys(relationshipMutation ?? {})
  if (profileNames.length === 0 && relationshipKeys.length === 0) return null

  const [open, setOpen] = useState(() => forceOpen ?? true)
  const [feedback, setFeedback] = useState('')

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (forceOpen !== undefined) setOpen(forceOpen)
  }, [forceOpen])

  const summaryParts: string[] = []
  if (profileNames.length > 0) summaryParts.push(`档案 · ${profileNames.join('、')}`)
  if (relationshipKeys.length > 0) summaryParts.push(`关系 · ${relationshipKeys.length} 条`)

  const handleRewrite = () => {
    if (!onRewrite || rewriting) return
    onRewrite(feedback)
    setFeedback('')
  }

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Bubble variant="ghost" className="text-xs">
        <CollapsibleTrigger className="cursor-pointer select-none text-rose-700 font-medium">
          🧬 档案/关系突变 · {summaryParts.join(' / ')}
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2 space-y-2">
          {profileNames.map((name) => (
            <div key={name} className="border-l-2 border-rose-200 pl-2">
              <div className="font-semibold text-[var(--c-text-secondary)]">{name}</div>
              {renderProfileFields(mutation![name])}
            </div>
          ))}
          {relationshipKeys.length > 0 && (
            <div className="border-l-2 border-rose-200 pl-2">
              <div className="font-semibold text-[var(--c-text-secondary)]">关系变更</div>
              {renderRelationshipEdges(relationshipMutation!)}
            </div>
          )}
          {onRewrite && (
            <div className="flex w-full items-center gap-1.5 pt-1">
              <Input
                type="text"
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    handleRewrite()
                  }
                }}
                placeholder="重写时怎么改（可选）…"
                disabled={rewriting}
                className="min-w-0 flex-1 text-xs disabled:bg-slate-100 disabled:text-slate-400"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={handleRewrite}
                disabled={rewriting}
                aria-label={rewriting ? '重写中…' : '重写突变'}
                title={rewriting ? '重写中…' : '重写突变'}
                className="shrink-0"
              >
                <RefreshCw size={14} aria-hidden className={rewriting ? 'animate-spin' : undefined} />
              </Button>
            </div>
          )}
        </CollapsibleContent>
      </Bubble>
    </Collapsible>
  )
}
