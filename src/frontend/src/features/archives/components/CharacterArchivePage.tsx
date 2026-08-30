import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useSelector } from 'react-redux'
import { Contact, Search } from 'lucide-react'
import { useArchiveOverview, useChapterArchives } from '@/shared/queries/archives'
import { useRelationshipGraph, useCast } from '@/shared/queries/setup'
import CharacterCard from '@/shared/components/CharacterCard'
import EmptyStateCard from '@/shared/components/EmptyStateCard'
import PageHeader from '@/shared/components/PageHeader'
import { filterCharactersByName } from '@/shared/utils/filterCharactersByName'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/shared/components/ui/input-group'
import { Label } from '@/shared/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { selectBackgroundJobs } from '@/shared/store/backgroundJobsSlice'
import { useActiveNovelId } from '@/shared/queries/novels'

interface Props {
  /** When true, render inside SetupPage (no duplicate page chrome). */
  embedded?: boolean
}

export default function CharacterArchivePage({ embedded = false }: Props) {
  const queryClient = useQueryClient()
  const novelId = useActiveNovelId()
  const { timelineCascadeActive } = useSelector(selectBackgroundJobs(novelId))
  const { data: overview = { built: [], plot_chapters: [] } } = useArchiveOverview()
  const [activeChapter, setActiveChapter] = useState<number | null>(null)
  const { data } = useChapterArchives(activeChapter)
  const { data: relationshipGraph } = useRelationshipGraph()
  const { data: cast = [] } = useCast()
  const portraitByName = useMemo(
    () => new Map(cast.map((c) => [c.name, Boolean(c.portrait_path?.trim())])),
    [cast],
  )
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [query, setQuery] = useState('')

  const toggleExpand = useCallback((name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }, [])

  useEffect(() => {
    const chapters = overview.plot_chapters.map((c) => c.chapter)
    setActiveChapter((prev) => (prev != null && chapters.includes(prev) ? prev : chapters[0] ?? null))
  }, [overview])

  useEffect(() => { setExpanded(new Set()) }, [activeChapter])

  useEffect(() => {
    if (!timelineCascadeActive) {
      void queryClient.invalidateQueries({ queryKey: ['archives'] })
    }
  }, [timelineCascadeActive, queryClient])

  const allCharacters = data?.characters ?? []
  const filtered = filterCharactersByName(allCharacters, query)
  const visibleNames = filtered.map((c) => c.name)
  const searching = query.trim().length > 0
  const allExpanded =
    visibleNames.length > 0 && visibleNames.every((name) => expanded.has(name))

  const toggleAllExpanded = () => {
    if (allExpanded) {
      setExpanded((prev) => {
        const next = new Set(prev)
        for (const name of visibleNames) next.delete(name)
        return next
      })
    } else {
      setExpanded((prev) => {
        const next = new Set(prev)
        for (const name of visibleNames) next.add(name)
        return next
      })
    }
  }

  const toolbar = overview.plot_chapters.length > 0 ? (
    <>
      <Label htmlFor="archive-chapter" className="text-xs text-[var(--c-text-muted)] shrink-0">
        章节
      </Label>
      <Select
        value={activeChapter != null ? String(activeChapter) : ''}
        onValueChange={(v) => setActiveChapter(Number(v))}
      >
        <SelectTrigger id="archive-chapter" aria-label="选择章节" className="w-auto min-w-32">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {overview.plot_chapters.map((c) => {
            const missing = c.roster.length - c.built.length
            return (
              <SelectItem key={c.chapter} value={String(c.chapter)}>
                第{c.chapter}章
                {missing > 0 ? (timelineCascadeActive ? '（推演中…）' : `（待构建 ${missing} 人）`) : ''}
              </SelectItem>
            )
          })}
        </SelectContent>
      </Select>
    </>
  ) : null

  const body = (
    <>
      {overview.plot_chapters.length === 0 && (
        <EmptyStateCard
          icon={Contact}
          message="尚未生成角色档案。在「对话」页编辑人物或章节后，引擎会在后台自动推演档案。"
        />
      )}
      {data && data.characters.length === 0 && (
        <EmptyStateCard
          icon={Contact}
          message={
            timelineCascadeActive
              ? `第${data.chapter}章档案推演中，完成后会自动出现在此。`
              : `第${data.chapter}章暂无档案，请在「对话」页触发相关编辑后等待后台推演。`
          }
        />
      )}
      {data && data.characters.length > 0 && (
        <div className="space-y-3 max-w-5xl">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="text-xs text-slate-400 tabular-nums shrink-0">
              {searching
                ? `共 ${allCharacters.length} 人 · 匹配 ${filtered.length}`
                : `共 ${allCharacters.length} 人`}
            </div>
            <InputGroup className="w-40">
              <InputGroupInput
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜索角色名"
                aria-label="搜索角色名"
              />
              <InputGroupAddon>
                <Search />
              </InputGroupAddon>
            </InputGroup>
            {visibleNames.length > 0 && (
              <button
                type="button"
                aria-pressed={allExpanded}
                onClick={toggleAllExpanded}
                className={`px-3 py-1 text-sm font-medium rounded-lg border transition-colors ${
                  allExpanded
                    ? 'bg-[var(--c-accent-subtle)] text-[var(--c-accent)] border-[var(--c-tag-violet-border)]'
                    : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                }`}
              >
                {allExpanded ? '全部折叠' : '全部展开'}
              </button>
            )}
          </div>
          {searching && filtered.length === 0 ? (
            <p className="text-sm text-slate-500">未找到匹配角色</p>
          ) : (
            filtered.map((c) => (
              <CharacterCard
                key={c.name}
                character={c}
                isOpen={expanded.has(c.name)}
                onToggle={() => toggleExpand(c.name)}
                relationshipGraph={relationshipGraph}
                hasPortrait={portraitByName.get(c.name) ?? false}
                showExpandedPortrait
              />
            ))
          )}
        </div>
      )}
    </>
  )

  if (embedded) {
    return (
      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        <div className="shrink-0 flex items-center gap-2 flex-wrap px-4 py-2 border-b border-[var(--c-border)] bg-[var(--c-surface)]">
          {toolbar}
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {body}
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden bg-app">
      <PageHeader
        title="角色档案"
        subtitle="按章节查看已生成的角色档案与状态时间线"
        actions={toolbar}
      />

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {body}
      </div>
    </div>
  )
}
