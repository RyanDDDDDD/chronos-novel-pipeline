import { RefreshCw } from 'lucide-react'
import { useDispatch, useSelector } from 'react-redux'
import ChatMarkdown from '@/shared/components/ChatMarkdown'
import PageHeader from '@/shared/components/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Label } from '@/shared/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { useChapterManuscript, useManuscriptChapters } from '@/features/manuscript/queries/manuscript'
import { useChapters, useChapterNumbers } from '@/shared/queries/chapters'
import { useActiveNovelId } from '@/shared/queries/novels'
import { countManuscriptChars } from '@/shared/utils/manuscriptText'
import { selectChapter, setChapter } from '@/shared/store/uiSlice'
import type { AppDispatch } from '@/shared/store/store'

export default function ChapterManuscriptPage() {
  const dispatch = useDispatch<AppDispatch>()
  const novelId = useActiveNovelId()
  const chapter = useSelector(selectChapter)
  const chapters = useChapterNumbers(novelId, chapter)
  const onSelectChapter = (ch: number) => dispatch(setChapter(ch))

  const { data: chapterMeta = [] } = useChapters(novelId)
  const { data: saved = [], refetch: refetchList, isFetching: listFetching } =
    useManuscriptChapters(novelId)
  const {
    data: manuscript,
    isLoading,
    isFetching,
    error,
    refetch,
  } = useChapterManuscript(novelId, chapter)

  const savedSet = new Set(saved.map(s => s.chapter))
  const titleByChapter = Object.fromEntries(
    chapterMeta.map(c => [c.chapter, c.title]),
  )

  const refresh = () => {
    void refetchList()
    void refetch()
  }

  const charCount = manuscript ? countManuscriptChars(manuscript.content) : 0

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden bg-app">
      <PageHeader
        title="章节成稿"
        subtitle="展示主笔页保存的整章文稿（含摘要与角色状态）"
        actions={
          <>
            <Label htmlFor="manuscript-chapter" className="text-xs text-[var(--c-text-muted)] shrink-0">
              章节
            </Label>
            <Select value={String(chapter)} onValueChange={(v) => onSelectChapter(Number(v))}>
              <SelectTrigger id="manuscript-chapter" className="w-auto min-w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {chapters.map(ch => {
                  const title = titleByChapter[ch]
                  const savedMark = savedSet.has(ch) ? ' · 已保存' : ''
                  const label = title ? `第${ch}章：${title}${savedMark}` : `第${ch}章${savedMark}`
                  return (
                    <SelectItem key={ch} value={String(ch)}>{label}</SelectItem>
                  )
                })}
              </SelectContent>
            </Select>
            <Button
              type="button"
              variant="outline"
              onClick={refresh}
              disabled={isFetching || listFetching}
              className="text-xs"
            >
              <RefreshCw size={14} className={isFetching || listFetching ? 'animate-spin' : ''} />
              刷新
            </Button>
            {manuscript && (
              <span className="text-xs text-[var(--c-text-muted)] tabular-nums shrink-0">
                {charCount.toLocaleString('zh-CN')} 字
              </span>
            )}
          </>
        }
      />

      <div className="flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-3xl mx-auto">
          {isLoading && (
            <p className="text-sm text-slate-400 text-center py-16">加载中…</p>
          )}
          {!isLoading && error && (
            <div className="rounded-lg bg-red-50 text-red-700 text-sm px-4 py-3">
              {error instanceof Error ? error.message : '加载失败'}
            </div>
          )}
          {!isLoading && !error && !manuscript && (
            <div className="text-center text-sm text-slate-400 py-16 space-y-2">
              <p>第 {chapter} 章尚无保存的主笔成稿。</p>
              <p className="text-xs">请先在「主笔」页运行并点击「保存」。</p>
            </div>
          )}
          {!isLoading && manuscript && (
            <article className="prose prose-slate max-w-none text-sm text-slate-800 leading-relaxed">
              <ChatMarkdown content={manuscript.content} />
            </article>
          )}
        </div>
      </div>
    </div>
  )
}
