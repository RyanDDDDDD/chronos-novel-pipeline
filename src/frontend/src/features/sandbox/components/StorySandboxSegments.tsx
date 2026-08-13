import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import ChatMarkdown from '@/shared/components/ChatMarkdown'
import CopyButton from '@/shared/components/CopyButton'
import { Button } from '@/shared/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'
import { Input } from '@/shared/components/ui/input'
import { FilterMenu } from '@/shared/components/mention/FilterMenu'
import { CharacterStateBubble } from '@/shared/components/CharacterStateBubble'
import { BASELINE_STATE_DERIVE_FIELDS, toCharacterList } from '@/shared/utils/characterStateFields'
import { EventLogBubble } from '@/shared/components/EventLogBubble'
import { ProfileMutationBubble } from '@/features/sandbox/components/ProfileMutationBubble'
import { RecallContextBubble } from '@/shared/components/RecallContextBubble'
import { RecalledSettingsBubble } from '@/shared/components/RecalledSettingsBubble'
import { RollingSummaryBubble } from '@/features/sandbox/components/RollingSummaryBubble'
import { SceneStateBubble } from '@/features/sandbox/components/SceneStateBubble'
import { SegmentLoadingRow } from '@/features/sandbox/components/SegmentLoadingRow'
import { useSetupSkills } from '@/shared/queries/setup'
import { memoryMetaLine } from '@/features/sandbox/utils/sandboxMemorySearch'
import type { CharacterState as SandboxCharacterState, Round } from '@/features/sandbox/hooks/useStorySandbox'
import type { SandboxMemoryEntry, StateDeriveFieldSpec } from '@/shared/types'
import { filterSlashMenu, plotExtensionSkills } from '@/shared/utils/setup'
import { detectRecognizedNames } from '@/shared/components/mention/mentionCandidates'
import { computeSelectionOffset } from '@/features/sandbox/utils/proseSelectionOffset'
import { splitProseForSelectionRewriteLoading } from '@/features/sandbox/utils/proseSelectionRewriteDisplay'
import {
  SANDBOX_DERIVE_FIELDS,
  type PendingDerivations,
  type SandboxDeriveField,
} from '@/features/sandbox/utils/sandboxDeriveFields'

/** Prose segment: the director's instruction bubble + the assistant's prose bubble, expanded,
 * plus an optional "rewrite" feedback box + button below. Takes only plain data plus the one
 * callback -- no knowledge of WS events or any protocol type. onRewrite is optional: when
 * provided (only ever passed for the latest round -- see TurnSegments), renders the feedback
 * input + button; when omitted, nothing extra renders. rewriting/rewritingProse are externally
 * driven (the panel owns the in-flight rewrite stream, mirroring liveRound) rather than a local
 * awaited-promise state, since a rewrite streams tokens over WS instead of resolving once.
 * characterNames/settingNames drive the same "识别到角色/识别到设定" preview line the main
 * composer shows -- no @ mention autocomplete here, rewrite feedback is a short instruction, not
 * a long turn. */
export function ProseBubble({
  instruction, prose, onRewrite, rewriting, rewritingProse, styleGuardRewriting,
  onRewriteSelection, selectionRewriting, selectionRewriteAnchor, selectionRewriteQueued,
  characterNames = [], settingNames = [], loadingStatus,
}: {
  instruction: string
  prose: string
  onRewrite?: (feedback: string) => void
  rewriting?: boolean
  rewritingProse?: string
  styleGuardRewriting?: boolean
  onRewriteSelection?: (originalText: string, anchorOffset: number, feedback: string) => void
  selectionRewriting?: boolean
  /** Selected fragment metadata for in-place loading UI while selectionRewriting is true. */
  selectionRewriteAnchor?: { originalText: string; anchorOffset: number }
  /** A selection-rewrite was requested for this round while busy elsewhere and is waiting to
   * auto-fire -- distinct from selectionRewriting (actually in flight right now). */
  selectionRewriteQueued?: boolean
  characterNames?: string[]
  settingNames?: string[]
  /** Status label (e.g. "思考中…") to show with a spinner in place of the prose while the live
   * round hasn't received its first token yet -- only ever passed for the in-progress liveRound,
   * never historical rounds, so it naturally stops once displayProse is non-empty. */
  loadingStatus?: string
}) {
  const [feedback, setFeedback] = useState('')
  const proseRef = useRef<HTMLDivElement>(null)
  const [menu, setMenu] = useState<{ x: number; y: number; text: string; offset: number } | null>(null)
  const [popover, setPopover] = useState<{ x: number; y: number; text: string; offset: number } | null>(null)
  const [selFeedback, setSelFeedback] = useState('')
  const menuPanelRef = useRef<HTMLDivElement>(null)

  const handleClick = () => {
    if (!onRewrite || rewriting) return
    onRewrite(feedback)
    setFeedback('')
  }

  useEffect(() => {
    if (!menu && !popover) return
    // A single-line <input> fires its own native 'scroll' event when its text overflows the
    // visible width (e.g. typing a long feedback string in the popover below) -- that must not
    // be mistaken for the user scrolling the page, so ignore any event whose target is inside
    // this menu/popover panel rather than closing on every scroll unconditionally.
    const closeAll = (e: Event) => {
      if (e.target instanceof Node && menuPanelRef.current?.contains(e.target)) return
      setMenu(null)
      setPopover(null)
    }
    window.addEventListener('mousedown', closeAll)
    window.addEventListener('scroll', closeAll, true)
    return () => {
      window.removeEventListener('mousedown', closeAll)
      window.removeEventListener('scroll', closeAll, true)
    }
  }, [menu, popover])

  const handleContextMenu = (e: React.MouseEvent) => {
    if (!onRewriteSelection || selectionRewriting) return
    const sel = window.getSelection()
    const text = sel?.toString() ?? ''
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed || !text.trim() || !proseRef.current) return
    const range = sel.getRangeAt(0)
    if (!proseRef.current.contains(range.startContainer)) return
    e.preventDefault()
    const offset = computeSelectionOffset(proseRef.current, range)
    setMenu({ x: e.clientX, y: e.clientY, text, offset })
    setPopover(null)
  }

  const handleMenuClick = () => {
    if (!menu) return
    setPopover(menu)
    setMenu(null)
  }

  const handleConfirmSelectionRewrite = () => {
    if (!popover || !onRewriteSelection) return
    onRewriteSelection(popover.text, popover.offset, selFeedback)
    setPopover(null)
    setSelFeedback('')
  }

  const recognizedNames = detectRecognizedNames(feedback, characterNames)
  const recognizedSettings = detectRecognizedNames(feedback, settingNames)

  const displayProse = rewriting ? (rewritingProse ?? '') : prose

  const selectionRewriteSplit = selectionRewriting && selectionRewriteAnchor
    ? splitProseForSelectionRewriteLoading(
      prose,
      selectionRewriteAnchor.originalText,
      selectionRewriteAnchor.anchorOffset,
    )
    : null

  const renderProseBody = () => {
    if (displayProse === '' && loadingStatus) {
      return (
        <span className="inline-flex items-center gap-1.5 italic text-slate-500">
          <Loader2 size={14} className="animate-spin shrink-0" aria-hidden />
          {loadingStatus}
        </span>
      )
    }
    if (selectionRewriteSplit) {
      return (
        <>
          {selectionRewriteSplit.head ? (
            <ChatMarkdown content={selectionRewriteSplit.head} />
          ) : null}
          <SegmentLoadingRow label="正在重写选中片段…" className="my-0.5" />
          {selectionRewriteSplit.tail ? (
            <ChatMarkdown content={selectionRewriteSplit.tail} />
          ) : null}
        </>
      )
    }
    return <ChatMarkdown content={displayProse} />
  }

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <div className="flex flex-col items-end max-w-[85%]">
          <div className="rounded-lg px-3 py-2 text-[length:var(--reading-font-size)] leading-relaxed bg-sky-100 text-sky-900">
            <ChatMarkdown content={instruction} />
          </div>
          <CopyButton
            text={instruction}
            className="mt-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          />
        </div>
      </div>
      <div className="flex justify-start">
        <div className="flex flex-col items-start max-w-[85%]">
          <div
            ref={proseRef}
            data-testid="prose-content"
            onContextMenu={handleContextMenu}
            className="rounded-lg px-3 py-2 text-[length:var(--reading-font-size)] leading-relaxed bg-slate-100 text-slate-800"
          >
            {renderProseBody()}
            {styleGuardRewriting && (
              <span className="ml-1 inline-block text-xs text-amber-600 animate-pulse">
                检测到 AI 味文本，正在重写…
              </span>
            )}
            {!selectionRewriting && selectionRewriteQueued && (
              <span className="ml-1 inline-block text-xs text-slate-400">
                已排队，将在当前任务完成后重写…
              </span>
            )}
          </div>
          {onRewrite ? (
            <div className="mt-1 w-full space-y-1">
              <div className="flex w-full items-center gap-1.5">
                <Input
                  type="text"
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      handleClick()
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
                  onClick={handleClick}
                  disabled={rewriting}
                  aria-label={rewriting ? '重写中…' : '重写这段'}
                  title={rewriting ? '重写中…' : '重写这段'}
                  className="shrink-0"
                >
                  <RefreshCw size={14} aria-hidden className={rewriting ? 'animate-spin' : undefined} />
                </Button>
                <CopyButton
                  text={displayProse}
                  className="shrink-0 text-slate-400 hover:bg-slate-200 hover:text-slate-600"
                />
              </div>
              {recognizedNames.length > 0 && (
                <p className="text-[11px] text-slate-400">识别到角色：{recognizedNames.join('、')}</p>
              )}
              {recognizedSettings.length > 0 && (
                <p className="text-[11px] text-slate-400">识别到设定：{recognizedSettings.join('、')}</p>
              )}
            </div>
          ) : (
            <CopyButton
              text={displayProse}
              className="mt-0.5 shrink-0 text-slate-400 hover:bg-slate-200 hover:text-slate-600"
            />
          )}
        </div>
      </div>
      {menu && (
        <div
          ref={menuPanelRef}
          className="fixed z-50 rounded-md border border-slate-200 bg-white shadow-float py-1"
          style={{ left: menu.x, top: menu.y }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            onClick={handleMenuClick}
            className="block w-full whitespace-nowrap px-3 py-1 text-left text-xs text-slate-700 hover:bg-slate-100"
          >
            重写选中片段
          </button>
        </div>
      )}
      {popover && (
        <div
          ref={menuPanelRef}
          className="fixed z-50 flex items-center gap-2 rounded-md border border-slate-200 bg-white shadow-float px-2 py-1.5"
          style={{ left: popover.x, top: popover.y }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <Input
            type="text"
            autoFocus
            value={selFeedback}
            onChange={(e) => setSelFeedback(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); handleConfirmSelectionRewrite() }
              if (e.key === 'Escape') { e.preventDefault(); setPopover(null) }
            }}
            placeholder="重写时怎么改（可选）…"
            className="w-48 text-xs"
          />
          <button
            type="button"
            onClick={handleConfirmSelectionRewrite}
            className="whitespace-nowrap text-xs text-slate-500 hover:text-slate-700"
          >
            重写
          </button>
        </div>
      )}
    </div>
  )
}

/** Pinned card above the composer showing directions picked from suggestion pills. */
export function SelectedDirectionsCard({
  directions,
  onRemove,
}: {
  directions: string[]
  onRemove: (text: string) => void
}) {
  if (directions.length === 0) return null
  return (
    <div className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 shadow-sm">
      <div className="text-xs font-medium text-sky-800 mb-1.5">🧭 已选剧情走向</div>
      <ul className="space-y-1">
        {directions.map((d) => (
          <li key={d} className="flex items-start gap-2 text-xs text-sky-900">
            <span className="flex-1 min-w-0">
              <ChatMarkdown content={`- ${d}`} />
            </span>
            <button
              type="button"
              aria-label={`移除 ${d}`}
              onClick={() => onRemove(d)}
              className="shrink-0 text-sky-500 hover:text-sky-800 leading-none px-0.5"
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Pinned card above the composer showing memories picked from the right panel's archived-memory
 * list. Uses --c-accent semantic tokens (not the sky-* palette SelectedDirectionsCard still uses)
 * for new UI -- the two cards intentionally don't match. */
export function SelectedMemoriesCard({
  memories,
  onRemove,
}: {
  memories: SandboxMemoryEntry[]
  onRemove: (id: string) => void
}) {
  if (memories.length === 0) return null
  return (
    <div className="rounded-lg border border-[var(--c-accent)] bg-[var(--c-accent-subtle)] px-3 py-2 shadow-sm">
      <div className="text-xs font-medium text-[var(--c-accent-text)] mb-1.5">🧠 已召回记忆</div>
      <ul className="space-y-1">
        {memories.map((m) => (
          <li key={m.id} className="flex items-start gap-2 text-xs text-[var(--c-accent-text)]">
            <span className="flex-1 min-w-0">{memoryMetaLine(m)}：{m.summary}</span>
            <button
              type="button"
              aria-label={`移除记忆 ${m.id}`}
              onClick={() => onRemove(m.id)}
              className="shrink-0 hover:opacity-70 leading-none px-0.5"
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Suggestions segment: unlocked (selectable) options default to expanded so the user can
 * click without an extra fold open; locked/submitted rounds stay collapsed. Also re-opens
 * when the user hits regenerate. Multi-select pills (toggle membership in `selected`, no
 * exclusivity) plus an optional regenerate-with-hint control below. onToggle only ever hands
 * the clicked text back to the caller -- it never sends/submits anything itself, and this
 * component does not own selection state (the caller does, since selection must survive across
 * every round's pills feeding one shared submission). onRegenerate is optional: when provided,
 * renders a hint input + regenerate button; when omitted (historical rounds), neither renders
 * at all. Fire-and-forget: this component doesn't track the request's outcome -- the caller is
 * responsible for showing a pending state (via pendingFields.suggestions, swapping this bubble
 * out for a loading placeholder) while the request is in flight. */
export function SuggestionsBubble({
  options, selected, onToggle, onRegenerate, locked = false, forceOpen,
}: {
  options: string[]
  selected: Set<string>
  onToggle?: (text: string) => void
  onRegenerate?: (hint: string) => void
  locked?: boolean
  /** Page-level "expand/collapse all" override -- imperatively set (like the lock-fold effect
   * below) since this bubble already manages `open` via a ref, not a controlled prop. */
  forceOpen?: boolean
}) {
  const { data: setupSkills } = useSetupSkills()
  const extensionSkills = useMemo(
    () => plotExtensionSkills(setupSkills ?? []),
    [setupSkills],
  )
  const [hint, setHint] = useState('')
  const [menuIdx, setMenuIdx] = useState(0)
  const [menuDismissed, setMenuDismissed] = useState(false)
  const [open, setOpen] = useState(false)
  const hintInputRef = useRef<HTMLInputElement>(null)
  const wasLocked = useRef(locked)
  const slashMenu = menuDismissed ? null : filterSlashMenu(hint, extensionSkills)
  useEffect(() => {
    setMenuIdx(0)
    if (!hint.startsWith('/')) setMenuDismissed(false)
  }, [hint])
  useEffect(() => {
    if (locked && !wasLocked.current) setOpen(false)
    wasLocked.current = locked
  }, [locked])
  useEffect(() => {
    if (forceOpen !== undefined) setOpen(forceOpen)
  }, [forceOpen])
  const canRetryEmpty = options.length === 0 && !locked && !!onRegenerate
  useLayoutEffect(() => {
    if (!locked && (options.length > 0 || canRetryEmpty)) setOpen(true)
  }, [locked, options.length, canRetryEmpty])
  // A malformed/empty LLM suggestion call degrades to options=[] rather than raising (see
  // direction_suggest.py::suggest_directions) so a bad call never breaks the turn that already
  // wrote prose -- but that must not also take the regenerate control down with it, or the user
  // is left with no way to retry. Only truly nothing-to-show (locked historical round, or no
  // onRegenerate at all) collapses to null.
  if (options.length === 0 && !canRetryEmpty) return null

  const openDetails = () => {
    setOpen(true)
  }

  const handleRegenerate = () => {
    if (!onRegenerate) return
    openDetails()
    onRegenerate(hint)
  }

  const pickSlash = (name: string) => {
    setHint(`/${name} `)
    hintInputRef.current?.focus()
  }

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="text-xs">
      <CollapsibleTrigger className="select-none cursor-pointer text-left text-[var(--c-accent)] font-medium">
        🧭 剧情走向选择 · {options.length > 0 ? `${options.length} 条` : '生成失败'}
        {locked ? ' · 已提交' : ''}
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2 flex flex-col gap-2">
        {canRetryEmpty && (
          <p className="text-xs text-slate-400">本轮走向建议生成失败或为空，可在下方重新生成</p>
        )}
        {options.map((o) => {
          const isSelected = selected.has(o)
          return (
            <button
              key={o}
              type="button"
              disabled={locked}
              aria-pressed={isSelected}
              className={
                isSelected
                  ? 'w-full text-left text-xs rounded-md border border-[var(--c-accent)] bg-[var(--c-accent)] text-[var(--c-accent-text)] px-3 py-2 disabled:opacity-90 disabled:cursor-not-allowed'
                  : 'w-full text-left text-xs rounded-md border border-[var(--c-accent)]/40 text-[var(--c-accent)] bg-[var(--c-accent-subtle)] px-3 py-2 hover:bg-[var(--c-accent-subtle)]/70 disabled:opacity-50 disabled:cursor-not-allowed'
              }
              onClick={() => onToggle?.(o)}
            >
              {o}
            </button>
          )
        })}
      </CollapsibleContent>
      {onRegenerate && !locked && (
        <div className="relative mt-2">
          <FilterMenu
            open={!!slashMenu && slashMenu.length > 0}
            items={slashMenu?.map((s) => ({ id: s.name, label: `/${s.name}`, sublabel: s.description })) ?? []}
            highlightedId={slashMenu?.[menuIdx]?.name}
            onSelect={pickSlash}
            onOpenChange={(next) => { if (!next) setMenuDismissed(true) }}
            anchor={<div className="pointer-events-none absolute inset-x-0 bottom-0" aria-hidden />}
          />
          <div className="flex items-center gap-2">
          <Input
            ref={hintInputRef}
            type="text"
            value={hint}
            onChange={(e) => setHint(e.target.value)}
            onKeyDown={(e) => {
              if (slashMenu && slashMenu.length > 0) {
                if (e.key === 'ArrowDown') {
                  e.preventDefault()
                  setMenuIdx((i) => (i + 1) % slashMenu.length)
                  return
                }
                if (e.key === 'ArrowUp') {
                  e.preventDefault()
                  setMenuIdx((i) => (i - 1 + slashMenu.length) % slashMenu.length)
                  return
                }
                if (e.key === 'Enter') {
                  e.preventDefault()
                  pickSlash(slashMenu[Math.min(menuIdx, slashMenu.length - 1)].name)
                  return
                }
                if (e.key === 'Escape') {
                  e.preventDefault()
                  setMenuDismissed(true)
                  return
                }
              }
              if (e.key === 'Enter') {
                e.preventDefault()
                handleRegenerate()
              }
            }}
            placeholder="给重新生成一点提示（可选，/ 选拓展 skill）…"
            className="flex-1 text-xs disabled:bg-slate-100 disabled:text-slate-400"
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={handleRegenerate}
            aria-label="重新生成走向"
            title="重新生成走向"
            className="shrink-0"
          >
            <RefreshCw size={14} aria-hidden />
          </Button>
          </div>
        </div>
      )}
    </Collapsible>
  )
}

export type TurnFilterCat = 'prose' | 'state' | 'suggestions'

export const TURN_FILTER_CATS: { cat: TurnFilterCat; label: string }[] = [
  { cat: 'prose', label: '正文' },
  { cat: 'state', label: '状态' },
  { cat: 'suggestions', label: '走向选择' },
]

/** Composes the three segments in order for one Round. Used identically for a completed
 * history round and the in-progress live round -- both are just Round-shaped data by the time
 * they reach here. Owns the filter-category show/hide logic; the three leaf components stay
 * filter-agnostic. isLatest gates whether onRegenerate reaches SuggestionsBubble -- regenerating
 * is scoped to the most recent completed round only. */
function DeriveFieldLoading({
  field, hiddenCats,
}: {
  field: SandboxDeriveField
  hiddenCats: Set<TurnFilterCat>
}) {
  const meta = SANDBOX_DERIVE_FIELDS[field]
  if (hiddenCats.has(meta.filterCat)) return null
  return <SegmentLoadingRow label={meta.label} variant={meta.variant} />
}

/** Maps pending derivation fields to loading rows; registry-driven for future fields. */
export function SandboxDeriveLoading({
  pendingFields,
  hiddenCats,
  fields,
}: {
  pendingFields?: PendingDerivations
  hiddenCats: Set<TurnFilterCat>
  fields: SandboxDeriveField[]
}) {
  if (!pendingFields) return null
  return (
    <>
      {fields.filter((f) => pendingFields[f]).map((field) => (
        <DeriveFieldLoading key={field} field={field} hiddenCats={hiddenCats} />
      ))}
    </>
  )
}

/** Standalone card for the opening-turn initial-state derivation — separate from the turn
 * dialogue so the user's first instruction only appears in the next card once init finishes. */
export function InitialContextCard({
  states,
  pending,
  scene,
  scenePending,
  hiddenCats,
  forceOpen,
  stateDeriveFields,
}: {
  states?: Record<string, SandboxCharacterState> | null
  pending?: boolean
  scene?: Record<string, unknown> | null
  scenePending?: boolean
  hiddenCats: Set<TurnFilterCat>
  forceOpen?: boolean
  stateDeriveFields?: StateDeriveFieldSpec[]
}) {
  const fields = stateDeriveFields ?? BASELINE_STATE_DERIVE_FIELDS
  if (hiddenCats.has('state')) return null
  if (!pending && !states && !scenePending && !scene) return null
  return (
    <div className="rounded-lg border border-slate-200 bg-white shadow-sm px-4 py-3 space-y-2">
      {pending ? (
        <DeriveFieldLoading field="initialStates" hiddenCats={hiddenCats} />
      ) : states ? (
        <CharacterStateBubble
          characters={toCharacterList(states, fields)} entry forceOpen={forceOpen}
          fields={fields}
        />
      ) : null}
      {scenePending ? (
        <DeriveFieldLoading field="initialSceneState" hiddenCats={hiddenCats} />
      ) : scene ? (
        <SceneStateBubble scene={scene} entry forceOpen={forceOpen} />
      ) : null}
    </div>
  )
}

export function TurnSegments({
  round, hiddenCats, selectedDirections, onToggleDirection, isLatest, onRegenerate, onRewrite,
  rewriting, rewritingProse, styleGuardRewriting, onRewriteSelection, selectionRewriting,
  selectionRewriteAnchor, selectionRewriteQueued, onRewriteProfileMutation, profileMutationRewriting,
  pendingFields, forceOpen,
  characterNames, settingNames, loadingStatus,
  stateDeriveFields,
}: {
  round: Round
  hiddenCats: Set<TurnFilterCat>
  selectedDirections: Set<string>
  onToggleDirection: (text: string) => void
  isLatest: boolean
  onRegenerate?: (hint: string) => void
  onRewrite?: (feedback: string) => void
  rewriting?: boolean
  rewritingProse?: string
  styleGuardRewriting?: boolean
  /** Unlike onRewrite/onRegenerate, not gated by isLatest below -- the selection-rewrite context
   * menu is meant to work on any already-completed round regardless of what's currently streaming
   * or deriving, so the caller decides per-round whether to pass this at all (see
   * StorySandboxPanel's per-round selectionRewritingRoundId/pendingSelectionRewrite comparison). */
  onRewriteSelection?: (originalText: string, anchorOffset: number, feedback: string) => void
  selectionRewriting?: boolean
  selectionRewriteAnchor?: { originalText: string; anchorOffset: number }
  /** This round has a selection-rewrite queued (busy elsewhere), not yet running. */
  selectionRewriteQueued?: boolean
  onRewriteProfileMutation?: (feedback: string) => void
  profileMutationRewriting?: boolean
  pendingFields?: PendingDerivations
  /** Page-level "expand/collapse all" override, forwarded to every fold-able bubble below. */
  forceOpen?: boolean
  /** Forwarded to ProseBubble's rewrite-feedback recognition preview; only meaningful when
   * onRewrite is also passed (isLatest round). */
  characterNames?: string[]
  settingNames?: string[]
  /** Forwarded to ProseBubble -- only ever passed for the in-progress liveRound (see
   * StorySandboxPanel), never historical rounds. */
  loadingStatus?: string
  stateDeriveFields?: StateDeriveFieldSpec[]
}) {
  const fields = stateDeriveFields ?? BASELINE_STATE_DERIVE_FIELDS
  const characterStates = round.characterStates ?? {}
  const showCharacterStates = !hiddenCats.has('state') && (
    pendingFields?.characterStates
    || Object.keys(characterStates).length > 0
  )
  const showSceneState = !hiddenCats.has('state') && (
    pendingFields?.sceneState
    || Object.keys(round.sceneState ?? {}).length > 0
  )
  const showSuggestions = !hiddenCats.has('suggestions') && (
    pendingFields?.suggestions
    || round.suggestions.length > 0
    // A suggest call that came back empty (see SuggestionsBubble's canRetryEmpty) must still
    // surface the regenerate control on the active round -- otherwise the whole segment
    // disappears with no way to retry.
    || (isLatest && !round.suggestionsLocked && !!onRegenerate)
  )

  return (
    <div className="rounded-lg border border-slate-200 bg-white shadow-sm px-4 py-3 space-y-2">
      {!hiddenCats.has('prose') && (
        <ProseBubble
          instruction={round.instruction} prose={round.prose}
          onRewrite={isLatest ? onRewrite : undefined}
          rewriting={isLatest ? rewriting : undefined}
          rewritingProse={isLatest ? rewritingProse : undefined}
          onRewriteSelection={onRewriteSelection}
          selectionRewriting={selectionRewriting}
          selectionRewriteAnchor={selectionRewriteAnchor}
          selectionRewriteQueued={selectionRewriteQueued}
          // Not gated by isLatest: the style-guard rewrite indicator also fires during a
          // still-streaming liveRound (isLatest=false there), which callers already scope
          // correctly on their end -- gating here a second time silently dropped it.
          styleGuardRewriting={styleGuardRewriting}
          characterNames={characterNames} settingNames={settingNames}
          loadingStatus={loadingStatus}
        />
      )}
      {!hiddenCats.has('state') && (
        <RecalledSettingsBubble recalledSettings={round.recalledSettings ?? []} forceOpen={forceOpen} />
      )}
      {!hiddenCats.has('state') && (
        <RecallContextBubble recallContext={round.recallContext ?? ''} forceOpen={forceOpen} />
      )}
      {showCharacterStates && (
        pendingFields?.characterStates ? (
          <DeriveFieldLoading field="characterStates" hiddenCats={hiddenCats} />
        ) : (
          <CharacterStateBubble
            characters={toCharacterList(characterStates, fields)}
            forceOpen={forceOpen}
            fields={fields}
          />
        )
      )}
      {showSceneState && (
        pendingFields?.sceneState ? (
          <DeriveFieldLoading field="sceneState" hiddenCats={hiddenCats} />
        ) : (
          <SceneStateBubble scene={round.sceneState ?? {}} forceOpen={forceOpen} />
        )
      )}
      {!hiddenCats.has('state') && (
        <EventLogBubble entries={round.eventLogEntries ?? []} forceOpen={forceOpen} />
      )}
      {(round.profileMutation || round.relationshipMutation) && !hiddenCats.has('state') && (
        <ProfileMutationBubble
          mutation={round.profileMutation}
          relationshipMutation={round.relationshipMutation}
          forceOpen={forceOpen}
          onRewrite={isLatest ? onRewriteProfileMutation : undefined}
          rewriting={isLatest ? profileMutationRewriting : undefined}
        />
      )}
      {round.rollingSummaryAfter && !hiddenCats.has('state') && (
        <RollingSummaryBubble summary={round.rollingSummaryAfter} forceOpen={forceOpen} />
      )}
      {showSuggestions && (
        pendingFields?.suggestions ? (
          <DeriveFieldLoading field="suggestions" hiddenCats={hiddenCats} />
        ) : (
          <SuggestionsBubble
            options={round.suggestions}
            selected={
              round.suggestionsLocked
                ? new Set(round.submittedDirections ?? [])
                : selectedDirections
            }
            locked={round.suggestionsLocked ?? false}
            onToggle={round.suggestionsLocked ? undefined : onToggleDirection}
            onRegenerate={isLatest && !round.suggestionsLocked ? onRegenerate : undefined}
            forceOpen={forceOpen}
          />
        )
      )}
    </div>
  )
}
