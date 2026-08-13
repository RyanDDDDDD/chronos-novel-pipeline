import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, BarChart3, BookOpen, Loader2, Search } from 'lucide-react'
import PageHeader from '@/shared/components/PageHeader'
import EmptyStateCard from '@/shared/components/EmptyStateCard'
import TokenUsageCounter from '@/features/stats/components/TokenUsageCounter'
import { useTokenStats } from '@/features/stats/queries/useTokenStats'
import {
  formatChapterKey,
  subsystemAccent,
  subsystemLabel,
} from '@/features/stats/utils/tokenStatsDisplay'
import {
  filterNovelsByTitle,
  toDashboardModel,
  type Cell,
  type NovelRow,
  type SubsystemRow,
} from '@/features/stats/utils/tokenStatsModel'
import { formatTokenCount } from '@/features/stats/utils/tokenUsage'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/table'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/shared/components/ui/accordion'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/shared/components/ui/input-group'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'

function LoadingSkeleton() {
  return (
    <div className="flex-1 overflow-y-auto bg-app p-4 sm:p-6 animate-pulse" aria-busy="true">
      <div className="max-w-5xl mx-auto space-y-6">
        <div className="h-8 w-40 rounded-lg bg-slate-200/80" />
        <div className="h-28 rounded-lg bg-slate-200/70" />
        <div className="h-48 rounded-lg bg-slate-200/60" />
      </div>
    </div>
  )
}

function ChapterTable({ rows }: { rows: SubsystemRow['chapters'] }) {
  if (rows.length === 0) return null
  return (
    <div className="mt-3 overflow-x-auto rounded-lg border border-slate-100">
      <Table className="min-w-[24rem] text-xs">
        <TableHeader>
          <TableRow>
            <TableHead>明细</TableHead>
            <TableHead className="text-right">输入</TableHead>
            <TableHead className="text-right">输出</TableHead>
            <TableHead className="text-right">缓存</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((ch) => (
            <TableRow key={ch.key}>
              <TableCell className="font-medium">{formatChapterKey(ch.key)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatTokenCount(ch.tokens_in)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatTokenCount(ch.tokens_out)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatTokenCount(ch.tokens_cached)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function SubsystemBlock({ sub }: { sub: SubsystemRow }) {
  return (
    <div className="px-4 py-4 border-t border-slate-100 first:border-t-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${subsystemAccent(sub.name)}`}>
          {subsystemLabel(sub.name)}
        </span>
        <TokenUsageCounter
          usage={sub.total}
          title={`${subsystemLabel(sub.name)} 小计`}
          tight
          className="ml-auto shrink-0"
        />
      </div>
      <ChapterTable rows={sub.chapters} />
    </div>
  )
}

function NovelCard({ novel }: { novel: NovelRow }) {
  return (
    <AccordionItem value={novel.novelId} className="rounded-lg border border-slate-200 bg-white shadow-sm overflow-hidden">
      <AccordionTrigger className="px-4 py-3 border-b border-slate-100 hover:bg-slate-50/60 transition-colors">
        <div className="flex flex-wrap items-center justify-between gap-3 flex-1">
          <div className="flex items-center gap-2 min-w-0">
            <BookOpen className="w-4 h-4 shrink-0 text-slate-400" aria-hidden />
            <Tooltip>
              <TooltipTrigger asChild>
                <h3 className="font-semibold text-slate-800 truncate">{novel.title}</h3>
              </TooltipTrigger>
              <TooltipContent>{novel.title}</TooltipContent>
            </Tooltip>
          </div>
          <TokenUsageCounter
            usage={novel.total}
            title={`${novel.title} 小计`}
            tight
            className="ml-auto"
          />
        </div>
      </AccordionTrigger>
      <AccordionContent>
        {novel.subsystems.length === 0 ? (
          <p className="px-4 py-4 text-sm text-slate-500">暂无子系统记录</p>
        ) : (
          novel.subsystems.map((sub) => (
            <SubsystemBlock
              key={sub.name}
              sub={sub}
            />
          ))
        )}
      </AccordionContent>
    </AccordionItem>
  )
}

function GrandTotalStrip({ total }: { total: Cell }) {
  return (
    <div
      className="text-xs sm:text-sm text-slate-500"
      title="全小说 token 合计"
    >
      <span className="text-slate-400">合计</span>{' '}
      <span className="text-slate-400">输入</span>{' '}
      <span className="tabular-nums font-medium text-slate-700">{formatTokenCount(total.tokens_in)}</span>
      <span className="mx-2 text-slate-300">·</span>
      <span className="text-slate-400">输出</span>{' '}
      <span className="tabular-nums font-medium text-slate-700">{formatTokenCount(total.tokens_out)}</span>
      <span className="mx-2 text-slate-300">·</span>
      <span className="text-slate-400">缓存</span>{' '}
      <span className="tabular-nums font-medium text-slate-700">{formatTokenCount(total.tokens_cached)}</span>
    </div>
  )
}

function TokenStatsLoaded({
  data,
  query,
  setQuery,
}: {
  data: NonNullable<ReturnType<typeof useTokenStats>['data']>
  query: string
  setQuery: (q: string) => void
}) {
  const model = useMemo(() => toDashboardModel(data), [data])
  const searching = query.trim().length > 0
  const filteredNovels = useMemo(
    () => filterNovelsByTitle(model.novels, query),
    [model, query],
  )
  const [openIds, setOpenIds] = useState<string[]>(() => model.novels.map((n) => n.novelId))
  // Force-reopen search matches, but only as a one-time nudge per distinct filtered set --
  // not a continuously-reasserted invariant. The latter (recomputing "must be open" from
  // scratch on every render via useMemo) would make it impossible to manually collapse a
  // currently-matching card while still searching, since the derived value snaps back open
  // on the very next render regardless of the user's click. Gating on filteredNovels
  // reference identity means this only re-fires when the query (and thus the matched set)
  // actually changes, so a collapse click alone (no further typing) sticks.
  useEffect(() => {
    if (!searching) return
    // openIds is an accumulator that must remember prior manual collapse/expand history across
    // renders; it is not purely derivable from (searching, filteredNovels) alone (that was the
    // earlier, buggy approach -- see comment above), so this genuinely needs effect-based
    // synchronization, not useMemo.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOpenIds((prev) => {
      const next = new Set(prev)
      for (const n of filteredNovels) next.add(n.novelId)
      return Array.from(next)
    })
  }, [searching, filteredNovels])

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden bg-app">
      <PageHeader
        icon={<BarChart3 className="w-5 h-5 text-[var(--c-tag-violet-text)]" aria-hidden />}
        title="Token 统计"
        subtitle={
          <>
            全库账本汇总 · 按小说与子系统拆分
            {model.novels.length > 0 && (
              <span className="text-[var(--c-text-faint)]">
                {' · '}
                {searching
                  ? `共 ${model.novels.length} 部 · 匹配 ${filteredNovels.length}`
                  : `${model.novels.length} 部小说`}
              </span>
            )}
          </>
        }
        actions={<GrandTotalStrip total={model.grandTotal} />}
      />
      <div className="flex-1 overflow-y-auto">
      <div className="max-w-5xl mx-auto p-4 sm:p-6 space-y-6">
        {model.novels.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-200 bg-white/60 px-6 py-12 text-center">
            <BarChart3 className="w-10 h-10 mx-auto text-slate-300 mb-3" aria-hidden />
            <p className="text-sm font-medium text-slate-600">暂无小说账本数据</p>
            <p className="text-xs text-slate-400 mt-1">运行主笔或设定流程后，消耗会记录在这里</p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <InputGroup className="flex-1 min-w-[12rem] max-w-sm">
                <InputGroupInput
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="搜索小说名称"
                  aria-label="搜索小说名称"
                />
                <InputGroupAddon>
                  <Search />
                </InputGroupAddon>
              </InputGroup>
            </div>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500 px-0.5">
              按小说
            </h2>
            {searching && filteredNovels.length === 0 ? (
              <EmptyStateCard
                icon={Search}
                message={`未找到匹配「${query.trim()}」的小说`}
              />
            ) : (
              <Accordion type="multiple" value={openIds} onValueChange={setOpenIds} className="space-y-3">
                {filteredNovels.map((novel) => (
                  <NovelCard key={novel.novelId} novel={novel} />
                ))}
              </Accordion>
            )}
          </div>
        )}
      </div>
      </div>
    </div>
  )
}

export default function TokenStatsDashboard() {
  const [query, setQuery] = useState('')
  const { data, isLoading, error } = useTokenStats()

  if (isLoading) {
    return (
      <div className="flex-1 flex flex-col min-h-0">
        <div className="flex items-center justify-center gap-2 py-3 text-slate-500 text-sm border-b border-slate-100 bg-white/80">
          <Loader2 className="w-4 h-4 animate-spin" aria-hidden />
          加载统计…
        </div>
        <LoadingSkeleton />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="flex flex-col items-center gap-2 text-center max-w-sm">
          <AlertCircle className="w-8 h-8 text-red-400" aria-hidden />
          <p className="text-sm font-medium text-red-600">无法加载 token 统计</p>
          <p className="text-xs text-slate-500">请确认后端已启动且账本接口可用</p>
        </div>
      </div>
    )
  }

  return <TokenStatsLoaded data={data} query={query} setQuery={setQuery} />
}
