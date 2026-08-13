import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useSelector } from 'react-redux'
import { PanelRight, PanelRightClose } from 'lucide-react'
import CharacterCard from '@/shared/components/CharacterCard'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { useSandboxCastArchives, useSandboxRelatedCastArchives, useSandboxMemoryArchive } from '@/features/sandbox/queries/storySandbox'
import { useRelationshipGraph, useCast } from '@/shared/queries/setup'
import { selectSandboxLiveProfileMutations, type LiveProfileMutation } from '@/features/sandbox/store/sandboxSlice'
import { mergeSandboxProfileOverlay } from '@/features/sandbox/utils/profileOverlay'
import { useFreshFieldKeys } from '@/features/sandbox/hooks/useFreshFieldKeys'
import { memorySearchText, memoryMetaLine } from '@/features/sandbox/utils/sandboxMemorySearch'
import type { CharacterArchive, RelationshipGraph, SandboxMemoryEntry } from '@/shared/types'

interface Props {
  novelId: string
  chapter: number
  activeCast: string[]
  branchId?: string | null
  selectedMemoryIds?: Set<string>
  onToggleMemory?: (entry: SandboxMemoryEntry) => void
}

const PANEL_COLLAPSE_KEY = 'chronos.sandboxCharacterPanel.collapsed'
const CHARACTERS_COLLAPSE_KEY = 'chronos.sandboxCharacterPanel.charactersCollapsed'
const MEMORY_COLLAPSE_KEY = 'chronos.sandboxCharacterPanel.memoryCollapsed'

function readCollapsed(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

function writeCollapsed(key: string, v: boolean): void {
  try {
    localStorage.setItem(key, v ? '1' : '0')
  } catch {
    /* persistence failure should not break UI */
  }
}

/** One character's card, with this round's live (not-yet-committed) profile_mutate overlay
 * merged on top of the REST-resolved baseline and a 5s highlight on whichever fields it just
 * touched. Split out from SandboxCharacterPanel so useFreshFieldKeys (a hook) can be called once
 * per character rather than inside a .map() callback. */
function SandboxCharacterCardEntry({
  archive, relationshipGraph, isOpen, onToggle, liveMutation, hasPortrait,
}: {
  archive: CharacterArchive
  relationshipGraph?: RelationshipGraph
  isOpen: boolean
  onToggle: () => void
  liveMutation?: LiveProfileMutation
  hasPortrait?: boolean
}) {
  const freshFields = useFreshFieldKeys(liveMutation)
  const character = liveMutation
    ? mergeSandboxProfileOverlay(archive, liveMutation.fields)
    : archive
  return (
    <CharacterCard
      character={character}
      relationshipGraph={relationshipGraph}
      isOpen={isOpen}
      onToggle={onToggle}
      highlightedFields={freshFields}
      hasPortrait={hasPortrait}
    />
  )
}

/** Group-level collapse header shared by both sections below -- a chevron + title button,
 * mirroring CharacterCard's own ▶/rotate-90 fold affordance. */
function GroupHeader({ title, isOpen, onToggle, trailing }: {
  title: string
  isOpen: boolean
  onToggle: () => void
  trailing?: ReactNode
}) {
  return (
    <div className="border-t border-slate-100">
      <Button
        type="button"
        variant="ghost"
        onClick={onToggle}
        aria-expanded={isOpen}
        className="w-full justify-start gap-2 px-3 py-2 h-auto text-left"
      >
        <span
          className={`text-slate-400 text-xs transition-transform duration-200 shrink-0 ${isOpen ? 'rotate-90' : ''}`}
          aria-hidden
        >
          ▶
        </span>
        <h2 className="text-xs font-semibold text-slate-700">{title}</h2>
      </Button>
      {isOpen && trailing}
    </div>
  )
}

/** Archived-memory browse section: search box + flat list, click toggles manual-recall
 * selection (owned by the caller -- see StorySandboxPage). */
function SandboxMemorySection({
  novelId, chapter, branchId, isOpen, onToggle, selectedIds, onToggleMemory,
}: {
  novelId: string
  chapter: number
  branchId: string | null
  isOpen: boolean
  onToggle: () => void
  selectedIds: Set<string>
  onToggleMemory: (entry: SandboxMemoryEntry) => void
}) {
  const [query, setQuery] = useState('')
  const { data, isLoading, isError } = useSandboxMemoryArchive(novelId, chapter, branchId)
  const entries = data ?? []
  const q = query.trim().toLowerCase()
  const filtered = q ? entries.filter((e) => memorySearchText(e).includes(q)) : entries

  return (
    <GroupHeader
      title="归档记忆"
      isOpen={isOpen}
      onToggle={onToggle}
      trailing={
        <div className="px-3 pb-3 space-y-2">
          <Input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索记忆…"
            className="text-xs"
          />
          {isLoading && <p className="text-xs text-slate-400 py-2 text-center">加载中…</p>}
          {isError && <p className="text-xs text-red-500 py-2 text-center">归档记忆加载失败</p>}
          {!isLoading && !isError && entries.length === 0 && (
            <p className="text-xs text-slate-500 py-2 text-center">暂无归档记忆</p>
          )}
          {!isLoading && !isError && entries.length > 0 && filtered.length === 0 && (
            <p className="text-xs text-slate-500 py-2 text-center">无匹配结果</p>
          )}
          <ul className="space-y-1.5">
            {filtered.map((e) => {
              const isSelected = selectedIds.has(e.id)
              return (
                <li key={e.id}>
                  <button
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => onToggleMemory(e)}
                    className={`w-full text-left rounded-md border px-2.5 py-2 text-xs transition-colors ${
                      isSelected
                        ? 'border-[var(--c-accent)] bg-[var(--c-accent-subtle)] text-[var(--c-accent-text)]'
                        : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                    }`}
                  >
                    <div className="text-[11px] text-slate-400 mb-0.5">{memoryMetaLine(e)}</div>
                    <div className="leading-relaxed">{e.summary}</div>
                    {e.characters.length > 0 && (
                      <div className="mt-1 text-[11px] text-slate-400">人物：{e.characters.join('、')}</div>
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      }
    />
  )
}

/** Story sandbox sidebar: character archives for present + related cast, plus a manual
 * archived-memory browse/recall section -- two independently collapsible groups. */
export default function SandboxCharacterPanel({
  novelId, chapter, activeCast, branchId = null,
  selectedMemoryIds = new Set(), onToggleMemory = () => {},
}: Props) {
  const [open, setOpen] = useState(() => !readCollapsed(PANEL_COLLAPSE_KEY))
  const [charactersOpen, setCharactersOpen] = useState(() => !readCollapsed(CHARACTERS_COLLAPSE_KEY))
  const [memoryOpen, setMemoryOpen] = useState(() => !readCollapsed(MEMORY_COLLAPSE_KEY))
  const [castTab, setCastTab] = useState<'present' | 'related'>('present')
  const { data: presentData, isLoading: presentLoading, isError: presentError } =
    useSandboxCastArchives(novelId, chapter, activeCast)
  const { data: relatedData, isLoading: relatedLoading, isError: relatedError } =
    useSandboxRelatedCastArchives(novelId, chapter, activeCast)

  const activeCastData = castTab === 'present' ? presentData : relatedData
  const activeCastLoading = castTab === 'present' ? presentLoading : relatedLoading
  const activeCastError = castTab === 'present' ? presentError : relatedError
  const { data: relationshipGraph } = useRelationshipGraph()
  const { data: cast = [] } = useCast()
  const portraitByName = useMemo(
    () => new Map(cast.map((c) => [c.name, Boolean(c.portrait_path?.trim())])),
    [cast],
  )
  const liveMutations = useSelector(selectSandboxLiveProfileMutations)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const castKey = activeCast.join(',')

  useEffect(() => { writeCollapsed(PANEL_COLLAPSE_KEY, !open) }, [open])
  useEffect(() => { writeCollapsed(CHARACTERS_COLLAPSE_KEY, !charactersOpen) }, [charactersOpen])
  useEffect(() => { writeCollapsed(MEMORY_COLLAPSE_KEY, !memoryOpen) }, [memoryOpen])

  useEffect(() => {
    setExpanded(new Set())
  }, [chapter, castKey])

  const toggleExpand = useCallback((name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }, [])

  const characterNames = activeCastData?.characters.map((c) => c.name) ?? []
  const allExpanded =
    characterNames.length > 0 && characterNames.every((name) => expanded.has(name))

  const toggleAllExpanded = () => {
    if (allExpanded) setExpanded(new Set())
    else setExpanded(new Set(characterNames))
  }

  const subtitle = chapter > 0 ? `第${chapter}章` : '自由模式'

  if (!open) {
    return (
      <aside className="w-10 shrink-0 border-l border-slate-200 bg-white flex flex-col items-center py-2">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={() => setOpen(true)}
          title="展开角色面板"
          aria-label="展开角色面板"
        >
          <PanelRight size={16} />
        </Button>
      </aside>
    )
  }

  return (
    // contain-layout: with many expanded cards this panel's content can run to several
    // thousand px tall. Without CSS containment, Chromium leaks that nested scroller's layout
    // overflow into `document.documentElement.scrollHeight`, producing a phantom whole-page
    // scrollbar and letting this panel's `sticky`/z-index children escape their stacking
    // context (visually overlapping the header's theme dropdown). contain-layout scopes both.
    <aside className="w-80 shrink-0 border-l border-slate-200 overflow-y-auto bg-white flex flex-col min-h-0 contain-layout">
      <div className="sticky top-0 z-10 bg-white border-b border-slate-100 px-3 py-2.5 flex items-center justify-between gap-2">
        <span className="text-[11px] text-slate-400 tabular-nums">{subtitle}</span>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={() => setOpen(false)}
          title="收起角色面板"
          aria-label="收起角色面板"
          className="shrink-0"
        >
          <PanelRightClose size={16} />
        </Button>
      </div>

      <GroupHeader
        title="角色档案"
        isOpen={charactersOpen}
        onToggle={() => setCharactersOpen((v) => !v)}
        trailing={
          <div className="px-3 pt-3 pb-3 space-y-2">
            <div className="flex gap-1" role="tablist">
              {(['present', 'related'] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={castTab === t}
                  onClick={() => setCastTab(t)}
                  className={`px-2 py-0.5 text-xs rounded-md border transition-colors ${
                    castTab === t
                      ? 'bg-[var(--c-accent)] text-[var(--c-accent-text)] border-[var(--c-accent)]'
                      : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                  }`}
                >
                  {t === 'present' ? '在场角色' : '相关角色'}
                </button>
              ))}
            </div>
            {characterNames.length > 0 && (
              <Button
                type="button"
                variant="outline"
                aria-pressed={allExpanded}
                onClick={toggleAllExpanded}
                className="h-auto w-full py-1 text-xs font-medium"
              >
                {allExpanded ? '全部折叠' : '全部展开'}
              </Button>
            )}
            {activeCastLoading && (
              <p className="text-xs text-slate-400 py-4 text-center">加载角色档案…</p>
            )}
            {activeCastError && (
              <p className="text-xs text-red-500 py-4 text-center">角色档案加载失败</p>
            )}
            {!activeCastLoading && !activeCastError && activeCastData && activeCastData.characters.length === 0 && (
              <p className="text-xs text-slate-500 py-4 text-center leading-relaxed">
                {castTab === 'present' ? '当前没有在场角色' : '当前没有相关角色'}
              </p>
            )}
            {activeCastData?.characters.map((c) => (
              <SandboxCharacterCardEntry
                key={c.name}
                archive={c}
                relationshipGraph={relationshipGraph}
                isOpen={expanded.has(c.name)}
                onToggle={() => toggleExpand(c.name)}
                liveMutation={liveMutations[c.name]}
                hasPortrait={portraitByName.get(c.name) ?? false}
              />
            ))}
          </div>
        }
      />

      <SandboxMemorySection
        novelId={novelId}
        chapter={chapter}
        branchId={branchId}
        isOpen={memoryOpen}
        onToggle={() => setMemoryOpen((v) => !v)}
        selectedIds={selectedMemoryIds}
        onToggleMemory={onToggleMemory}
      />
    </aside>
  )
}
