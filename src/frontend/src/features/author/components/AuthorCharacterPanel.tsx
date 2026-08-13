import { useCallback, useEffect, useMemo, useState } from 'react'
import { PanelRight, PanelRightClose } from 'lucide-react'
import CharacterCard from '@/shared/components/CharacterCard'
import { Button } from '@/shared/components/ui/button'
import { useChapterArchives } from '@/shared/queries/archives'
import { useCast, useRelationshipGraph } from '@/shared/queries/setup'

interface Props {
  chapter: number
}

const COLLAPSE_KEY = 'chronos.authorCharacterPanel.collapsed'

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1'
  } catch {
    return false
  }
}

function writeCollapsed(v: boolean): void {
  try {
    localStorage.setItem(COLLAPSE_KEY, v ? '1' : '0')
  } catch {
    /* 持久化失败不影响功能 */
  }
}

/** 主笔页右侧：当前章节的角色档案卡（数据经 archives repository / API）。*/
export default function AuthorCharacterPanel({ chapter }: Props) {
  const [open, setOpen] = useState(() => !readCollapsed())
  const { data, isLoading, isError } = useChapterArchives(chapter)
  const { data: relationshipGraph } = useRelationshipGraph()
  const { data: cast = [] } = useCast()
  const portraitByName = useMemo(
    () => new Map(cast.map((c) => [c.name, Boolean(c.portrait_path?.trim())])),
    [cast],
  )
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  useEffect(() => {
    writeCollapsed(!open)
  }, [open])

  useEffect(() => {
    setExpanded(new Set())
  }, [chapter])

  const toggleExpand = useCallback((name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }, [])

  const characterNames = data?.characters.map((c) => c.name) ?? []
  const allExpanded =
    characterNames.length > 0 && characterNames.every((name) => expanded.has(name))

  const toggleAllExpanded = () => {
    if (allExpanded) setExpanded(new Set())
    else setExpanded(new Set(characterNames))
  }

  if (!open) {
    return (
      <aside className="w-10 shrink-0 border-l border-slate-200 bg-white flex flex-col items-center py-2">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={() => setOpen(true)}
          title="展开角色档案"
          aria-label="展开角色档案"
        >
          <PanelRight size={16} />
        </Button>
      </aside>
    )
  }

  return (
    <aside className="w-80 shrink-0 border-l border-slate-200 overflow-y-auto bg-white flex flex-col min-h-0">
      <div className="sticky top-0 z-10 bg-white border-b border-slate-100 px-3 py-2.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-baseline gap-2 min-w-0">
            <h2 className="text-xs font-semibold text-slate-700">本章角色档案</h2>
            <span className="text-[11px] text-slate-400 tabular-nums shrink-0">第{chapter}章</span>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => setOpen(false)}
            title="收起角色档案"
            aria-label="收起角色档案"
            className="shrink-0"
          >
            <PanelRightClose size={16} />
          </Button>
        </div>
        {characterNames.length > 0 && (
          <Button
            type="button"
            variant="outline"
            aria-pressed={allExpanded}
            onClick={toggleAllExpanded}
            className="mt-2 h-auto w-full py-1 text-xs font-medium"
          >
            {allExpanded ? '全部折叠' : '全部展开'}
          </Button>
        )}
      </div>

      <div className="flex-1 p-3 space-y-2">
        {isLoading && (
          <p className="text-xs text-slate-400 py-4 text-center">加载角色档案…</p>
        )}
        {isError && (
          <p className="text-xs text-red-500 py-4 text-center">角色档案加载失败</p>
        )}
        {!isLoading && !isError && data && data.characters.length === 0 && (
          <p className="text-xs text-slate-500 py-4 text-center leading-relaxed">
            第{chapter}章暂无角色档案，请在设定对话中派生 timeline。
          </p>
        )}
        {data?.characters.map((c) => (
          <CharacterCard
            key={c.name}
            character={c}
            relationshipGraph={relationshipGraph}
            isOpen={expanded.has(c.name)}
            onToggle={() => toggleExpand(c.name)}
            hasPortrait={portraitByName.get(c.name) ?? false}
          />
        ))}
      </div>
    </aside>
  )
}
