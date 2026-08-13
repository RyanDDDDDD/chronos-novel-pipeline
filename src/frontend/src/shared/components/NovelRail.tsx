import { useEffect, useMemo, useState } from 'react'
import { useSelector, useDispatch } from 'react-redux'
import { useNavigate, useParams } from 'react-router-dom'
import { Plus, MoreHorizontal, PanelLeftClose, PanelLeft, Pencil, Trash2, Copy, Search } from 'lucide-react'
import NovelRailSettings from '@/shared/components/NovelRailSettings'
import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import ServiceStatusIcons from '@/shared/components/ServiceStatusIcons'
import { useNovels, useActiveNovelId, useNovelActions, useNovelStatusSnapshot } from '@/shared/queries/novels'
import { selectNovelRunStatus, novelStatusAcknowledged } from '@/shared/store/novelStatusSlice'
import type { AppDispatch } from '@/shared/store/store'
import { fetchServiceStatus } from '@/shared/api/servicePing'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/shared/components/ui/input-group'
import { filterNovelsByName } from '@/shared/utils/novels'

const COLLAPSE_KEY = 'chronos.novelRail.collapsed'

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
    /*Ignore: persistence failure does not affect functionality*/
  }
}

function NovelStatusDot({ novelId }: { novelId: string }) {
  const status = useSelector(selectNovelRunStatus(novelId))
  const dispatch = useDispatch<AppDispatch>()
  useEffect(() => {
    if (status !== 'done') return
    const t = setTimeout(() => dispatch(novelStatusAcknowledged({ novelId })), 3000)
    return () => clearTimeout(t)
  }, [status, novelId, dispatch])
  if (status === 'idle') return null
  const cls =
    status === 'running' ? 'bg-red-500 animate-pulse'
    : status === 'done' ? 'bg-emerald-500 animate-pulse'
    : 'bg-red-600'
  return (
    <span
      className={`absolute -right-0.5 -top-0.5 size-2 rounded-full ${cls}`}
      title={status === 'error' ? '运行出错' : status === 'running' ? '后台运行中' : '刚刚完成'}
    />
  )
}

/** Left novel bar (Cursor style): can be folded into a narrow icon bar; list items are hovered out of the ⋯ menu (copy/rename/delete).*/
export default function NovelRail() {
  const navigate = useNavigate()
  const novelId = useParams().novelId ?? ''
  const { data: novels = [] } = useNovels()
  const activeId = useActiveNovelId()
  useNovelStatusSnapshot()
  const { createNovel, copyNovel, renameNovel, deleteNovel } = useNovelActions()
  // Switching novels always lands on its dialogue (chat) page, regardless of the view being left.
  const onSwitch = (id: string) => { if (id !== novelId) navigate(`/novel/${id}/chat`) }

  const [collapsed, setCollapsed] = useState<boolean>(readCollapsed)
  const [menuId, setMenuId] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const filteredNovels = useMemo(() => filterNovelsByName(novels, query), [novels, query])
  const searching = query.trim().length > 0

  useEffect(() => {
    writeCollapsed(collapsed)
  }, [collapsed])

  const dispatch = useDispatch<AppDispatch>()

  useEffect(() => {
    void fetchServiceStatus(dispatch)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const toggle = () => setCollapsed(v => !v)
  const canDelete = novels.length > 1

  if (collapsed) {
    return (
      <nav className="flex flex-col items-center gap-1 w-12 shrink-0 h-full min-h-0 border-r border-slate-200 bg-white py-2">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button type="button" variant="ghost" size="icon" onClick={toggle} aria-label="展开小说栏"
              className="shrink-0 rounded-lg text-slate-400 hover:text-slate-600">
              <PanelLeft size={16} />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="right">展开小说栏</TooltipContent>
        </Tooltip>
        <div className="flex flex-col items-center gap-1 mt-1 flex-1 min-h-0 w-full overflow-y-auto scrollbar-hidden">
          {filteredNovels.map(n => (
            <Tooltip key={n.id}>
              <TooltipTrigger asChild>
                <button
                  onClick={() => onSwitch(n.id)}
                  aria-label={n.name}
                  className={`relative shrink-0 size-8 min-w-8 min-h-8 rounded-lg text-sm font-semibold leading-none flex items-center justify-center transition-colors ${
                    n.id === activeId
                      ? 'bg-[var(--c-accent-subtle)] text-[var(--c-accent)] before:absolute before:left-0 before:top-1 before:bottom-1 before:w-0.5 before:rounded-full before:bg-[var(--c-accent)]'
                      : 'bg-[var(--c-surface-hover)] text-[color:var(--c-text-muted)] hover:bg-[var(--c-border)]'
                  }`}
                >
                  {n.name.slice(0, 1)}
                  <NovelStatusDot novelId={n.id} />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right">{n.name}</TooltipContent>
            </Tooltip>
          ))}
        </div>
        <div className="shrink-0 border-t border-slate-100 pt-1 w-full flex justify-center">
          <ServiceStatusIcons collapsed />
        </div>
        <div className="shrink-0 flex flex-col items-center gap-1 mt-1 w-full px-1">
          <NovelRailSettings novelId={novelId} collapsed />
          <Tooltip>
            <TooltipTrigger asChild>
              <Button type="button" variant="ghost" size="icon" onClick={createNovel} aria-label="新建小说"
                className="shrink-0 size-8 min-w-8 min-h-8 rounded-lg text-slate-400 hover:text-slate-600">
                <Plus size={16} />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">新建小说</TooltipContent>
          </Tooltip>
        </div>
      </nav>
    )
  }

  return (
    <nav className="flex flex-col w-56 shrink-0 h-full min-h-0 border-r border-slate-200 bg-white">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-100">
        <span className="text-xs font-semibold text-slate-500 tracking-wide">小说</span>
        <div className="flex items-center gap-0.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button type="button" variant="ghost" size="icon" onClick={toggle} aria-label="折叠小说栏"
                className="rounded text-slate-400 hover:text-slate-600">
                <PanelLeftClose size={15} />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">折叠小说栏</TooltipContent>
          </Tooltip>
        </div>
      </div>

      <div className="shrink-0 px-2 pb-2 border-b border-slate-100">
        <InputGroup>
          <InputGroupInput
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索小说"
            aria-label="搜索小说"
          />
          <InputGroupAddon>
            <Search />
          </InputGroupAddon>
        </InputGroup>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto py-1 scrollbar-hidden">
        {searching && filteredNovels.length === 0 ? (
          <p className="px-3 py-2 text-xs text-[color:var(--c-text-muted)]">
            {`未找到匹配「${query.trim()}」的小说`}
          </p>
        ) : null}
        {filteredNovels.map(n => {
          const active = n.id === activeId
          return (
            <div key={n.id} className="group relative px-1.5">
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => onSwitch(n.id)}
                    className={`relative w-full text-left pl-3 pr-7 py-1.5 text-sm rounded-lg transition-colors ${
                      active
                        ? 'bg-[var(--c-accent-subtle)] text-[var(--c-accent)] font-medium hover:text-[var(--c-accent-hover)]'
                        : 'text-[color:var(--c-text-secondary)] hover:bg-[var(--c-surface-hover)]'
                    }`}
                  >
                    <span className="block truncate">{n.name}</span>
                    <NovelStatusDot novelId={n.id} />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="right">{n.name}</TooltipContent>
              </Tooltip>
              <DropdownMenu open={menuId === n.id} onOpenChange={(open) => setMenuId(open ? n.id : null)}>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    title="更多"
                    className={`absolute right-2 top-1/2 -translate-y-1/2 h-auto w-auto p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-200 ${
                      menuId === n.id ? '' : 'opacity-0 group-hover:opacity-100'
                    }`}
                  >
                    <MoreHorizontal size={14} />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-32">
                  <DropdownMenuItem onClick={() => void copyNovel(n.id)}>
                    <Copy size={13} />复制
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => void renameNovel(n.id)}>
                    <Pencil size={13} />重命名
                  </DropdownMenuItem>
                  <DropdownMenuItem variant="destructive" disabled={!canDelete} onClick={() => void deleteNovel(n.id)}>
                    <Trash2 size={13} />删除
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          )
        })}
      </div>

      <div className="shrink-0 border-t border-slate-100">
        <ServiceStatusIcons collapsed={false} />
      </div>

      <div className="shrink-0 border-t border-slate-100 px-1.5 py-2 flex flex-col gap-1">
        <NovelRailSettings novelId={novelId} collapsed={false} />
        <Button
          type="button"
          variant="ghost"
          onClick={createNovel}
          className="w-full justify-start gap-2 px-2.5 py-1.5 text-xs font-medium text-[color:var(--c-text-muted)] rounded-lg"
        >
          <Plus size={14} className="shrink-0" aria-hidden />
          新建小说
        </Button>
      </div>
    </nav>
  )
}
