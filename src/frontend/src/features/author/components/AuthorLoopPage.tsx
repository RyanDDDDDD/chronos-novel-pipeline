import { useState, useEffect, useRef } from 'react'
import { useSelector, useDispatch } from 'react-redux'
import { useNavigate, useParams } from 'react-router-dom'
import { PenLine, Loader2, CheckCircle2, AlertTriangle, Play, Square, RotateCcw, FileText } from 'lucide-react'

import AuthorCharacterPanel from '@/features/author/components/AuthorCharacterPanel'
import AuthorSceneImageRow from '@/features/author/components/AuthorSceneImageRow'
import { CharacterStateBubble } from '@/shared/components/CharacterStateBubble'
import { EventLogBubble } from '@/shared/components/EventLogBubble'
import { RecallContextBubble } from '@/shared/components/RecallContextBubble'
import PageHeader from '@/shared/components/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { useStateDeriveFields } from '@/shared/queries/stateDeriveFields'
import type { AuthorMessage } from '@/shared/types'
import { parseCharacterPerformance, resolveCharacterSegment } from '@/features/author/utils/characterPerformance'
import { stripSynthesisProse } from '@/features/author/utils/synthesisProse'
import {
  authorContextGroupHasContent,
  buildAuthorTimelineItems,
  type AuthorContextGroup,
} from '@/features/author/utils/authorTimeline'
import { useActiveNovelId } from '@/shared/queries/novels'
import { useChapterNumbers } from '@/shared/queries/chapters'
import { useAuthorSceneImages, requestAuthorSceneImage } from '@/features/author/queries/sceneImage'
import { useToast } from '@/shared/hooks/useToast'
import { selectAuthorLoop, startAuthorLoop, resumeAuthorLoop, restartAuthorLoop, stopAuthorLoop } from '@/features/author/store/authorLoopSlice'
import { selectAuthorSceneImageLastFailure, authorSceneImageFailureConsumed } from '@/shared/store/authorSceneImageSlice'
import { selectChapter, setChapter as setChapterAction } from '@/shared/store/uiSlice'
import { selectBusy, selectResumable } from '@/shared/store/selectors'
import { VIEW_LABELS } from '@/shared/utils/novelRoute'
import type { AppDispatch, RootState } from '@/shared/store/store'

/** dialogue agent → Chinese label; no agent → empty string.*/
export function agentLabel(agent?: string, role?: string): string {
  if (agent === 'director') return '导演·旁白'
  if (agent === 'character') return `角色·${role ?? '?'}`
  if (agent === 'synthesis') return '合成·正文'
  return ''
}

const AGENT_CHIP: Record<string, string> = {
  director: 'bg-amber-100 text-amber-700',
  character: 'bg-sky-100 text-sky-700',
  synthesis: 'bg-[var(--c-tag-violet-bg)] text-[var(--c-tag-violet-text)]',
}

/** The timeline can display and hide agent output categories according to labels (labels are only available in dialogue mode).*/
export type AuthorFilterCat = 'director' | 'character' | 'synthesis' | 'state' | 'summary'

//The label is short and deliberately different from the agent logo copy (director·narration/compositing·text) in the bubble to avoid selector ambiguity.
const FILTER_CATS: { cat: AuthorFilterCat; label: string; chip: string }[] = [
  { cat: 'director', label: '导演', chip: 'bg-amber-100 text-amber-700' },
  { cat: 'character', label: '角色表演', chip: 'bg-sky-100 text-sky-700' },
  { cat: 'synthesis', label: '合成正文', chip: 'bg-[var(--c-tag-violet-bg)] text-[var(--c-tag-violet-text)]' },
  { cat: 'state', label: '角色状态', chip: 'bg-emerald-100 text-emerald-700' },
  { cat: 'summary', label: '摘要', chip: 'bg-amber-50 text-amber-700' },
]

/** Streaming live agent → category; non-agent tag → null.*/
function liveCategory(agent: string): AuthorFilterCat | null {
  return agent === 'director' || agent === 'character' || agent === 'synthesis' ? agent : null
}

/** Message → filterable category; no tags (non-conversation segments/interaction traces/user responses) → null (never filtered).*/
export function messageCategory(m: AuthorMessage): AuthorFilterCat | null {
  if (m.type === 'state' || m.type === 'event_log' || m.type === 'recall') return 'state'
  if (m.type === 'summary') return 'summary'
  if (m.type === 'segment') return liveCategory(m.segment.agent ?? '')
  return null
}

function AgentBadge({ agent, role }: { agent?: string; role?: string }) {
  const label = agentLabel(agent, role)
  if (!label || !agent) return null
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${AGENT_CHIP[agent] ?? 'bg-slate-100 text-slate-500'}`}>
      {label}
    </span>
  )
}

/** Agent bubble on the left (main author/system).*/
function AgentBubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-lg rounded-tl-sm bg-white border border-slate-200 shadow-sm px-4 py-3">
        {children}
      </div>
    </div>
  )
}

/** Single paragraph text bubble: truncate if it is too long + click to expand/collapse (long paragraphs are folded by default and need to be expanded manually).*/
/** Per-beat recall + character state + event archive, merged into one agent bubble. */
function AuthorContextBubble({ group }: { group: AuthorContextGroup }) {
  const { fields } = useStateDeriveFields()
  if (!authorContextGroupHasContent(group)) return null

  return (
    <AgentBubble>
      <div className="space-y-2">
        {group.recall && (
          <RecallContextBubble recallContext={group.recall.recallContext} />
        )}
        {group.state && group.state.characters.length > 0 && (
          <CharacterStateBubble
            characters={group.state.characters}
            entry={group.state.entry}
            fields={fields}
          />
        )}
        {group.event && group.event.events.some((e) => e.summary) && (
          <EventLogBubble entries={group.event.events} />
        )}
      </div>
    </AgentBubble>
  )
}

/** Summary bubble: Neutral summary of this beat (memory across beat events).*/
function SummaryBubble({ text }: { text: string }) {
  if (!text.trim()) return null
  return (
    <AgentBubble>
      <div className="text-xs text-amber-700 font-medium mb-1">📌 摘要（本 beat 梗概）</div>
      <div className="text-xs text-slate-500 whitespace-pre-wrap leading-relaxed">{text}</div>
    </AgentBubble>
  )
}

const SEG_FOLD_CHARS = 360

function CharacterPerformanceFields({
  text,
  intent,
  psychology,
  folded,
  expanded,
  onToggle,
}: {
  text: string
  intent?: string
  psychology?: string
  folded: boolean
  expanded: boolean
  onToggle: () => void
}) {
  const long = text.length > SEG_FOLD_CHARS
  const shown = folded ? text.slice(0, SEG_FOLD_CHARS) : text
  return (
    <>
      {intent && (
        <div className="text-xs mb-2 p-2 rounded border whitespace-pre-wrap text-[var(--c-tag-violet-text)] bg-[var(--c-tag-violet-bg)] border-[var(--c-tag-violet-border)]">
          <span className="font-semibold">💃 动作意图：</span>{intent}
        </div>
      )}
      {psychology && (
        <div className="text-xs mb-2 p-2 rounded border whitespace-pre-wrap text-indigo-600 bg-indigo-50 border-indigo-100">
          <span className="font-semibold">🧠 心理活动：</span>{psychology}
        </div>
      )}
      <div className="text-xs text-slate-500 font-medium mb-1">💬 台词</div>
      <div className={`relative text-sm text-slate-700 whitespace-pre-wrap leading-relaxed${folded ? ' max-h-[12rem] overflow-hidden' : ''}`}>
        {text ? shown : <span className="text-slate-300">（无台词）</span>}
        {folded && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-white to-transparent" />
        )}
      </div>
      {long && (
        <Button
          type="button"
          variant="link"
          onClick={onToggle}
          className="mt-1 h-auto p-0 no-underline text-xs text-[var(--c-accent)] hover:text-[var(--c-accent-hover)]"
        >
          {expanded ? '收起' : `展开全文（${text.length} 字）`}
        </Button>
      )}
    </>
  )
}

function SegmentBubble({ seg, chapter, sceneImageUrl, onGenerateSceneImage }: {
  seg: { index: number; beat?: number; beats?: number; intent: string; psychology?: string; skill: string | null; text: string; draft?: boolean; agent?: string; role?: string }
  chapter?: number
  sceneImageUrl?: string
  onGenerateSceneImage?: () => void
}) {
  const isCharacter = seg.agent === 'character'
  const isSynthesis = seg.agent === 'synthesis'
  const charPerf = isCharacter ? resolveCharacterSegment(seg) : null
  const bodyText = isSynthesis ? stripSynthesisProse(seg.text) : seg.text
  const long = bodyText.length > SEG_FOLD_CHARS
  const [expanded, setExpanded] = useState(false)
  const folded = long && !expanded
  const shown = folded ? bodyText.slice(0, SEG_FOLD_CHARS) : bodyText
  //beat label: single section is marked with multiple beats "Nth section · beat M/T"; single beat of the whole section is marked with segment only
  const label = seg.beat != null && (seg.beats ?? 1) > 1
    ? `第 ${seg.index + 1} 段 · beat ${seg.beat + 1}/${seg.beats}`
    : `第 ${seg.index + 1} 段`
  return (
    <AgentBubble>
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-xs font-semibold text-slate-500">{label}</span>
        <AgentBadge agent={seg.agent} role={seg.role} />
        {seg.draft && <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">草稿</span>}
      </div>
      {isCharacter && charPerf ? (
        <CharacterPerformanceFields
          text={charPerf.dialogue}
          intent={charPerf.intent}
          psychology={charPerf.psychology}
          folded={folded}
          expanded={expanded}
          onToggle={() => setExpanded(v => !v)}
        />
      ) : (
        <>
          {seg.intent && (
            <details className="mb-2 text-xs text-slate-500">
              <summary className="cursor-pointer select-none text-slate-400 hover:text-slate-600">
                📄 原文底稿（{seg.intent.length} 字）
              </summary>
              <div className="mt-1 whitespace-pre-wrap p-2 rounded border border-slate-100 bg-slate-50 text-slate-500">
                {seg.intent}
              </div>
            </details>
          )}
          <div className={`relative text-sm text-slate-700 whitespace-pre-wrap leading-relaxed${folded ? ' max-h-[12rem] overflow-hidden' : ''}`}>
            {bodyText ? shown : <span className="text-slate-300">（空）</span>}
            {folded && (
              <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-white to-transparent" />
            )}
          </div>
          {long && (
            <Button
              type="button"
              variant="link"
              onClick={() => setExpanded(v => !v)}
              className="mt-1 h-auto p-0 no-underline text-xs text-[var(--c-accent)] hover:text-[var(--c-accent-hover)]"
            >
              {expanded ? '收起' : `展开全文（${bodyText.length} 字）`}
            </Button>
          )}
        </>
      )}
      {/* bodyText, not seg.text -- a stage whose prose strips down to whitespace has nothing
          to draw, and the bubble already renders it as （空）. */}
      {isSynthesis && bodyText.trim() && onGenerateSceneImage && (
        <AuthorSceneImageRow
          chapter={chapter ?? 0}
          index={seg.index}
          imageUrl={sceneImageUrl}
          onGenerate={onGenerateSceneImage}
        />
      )}
    </AgentBubble>
  )
}

/**
 *The main writer’s paragraph-by-paragraph writing view (chat style): agent bubbles on the left.
 *Timeline messages (segment/state/summary) are retained throughout the process.
 */
export default function AuthorLoopPage() {
  const dispatch = useDispatch<AppDispatch>()
  const navigate = useNavigate()
  const novelId = useParams().novelId ?? ''
  const chapter = useSelector(selectChapter)
  const chapters = useChapterNumbers(useActiveNovelId(), chapter)
  const authorLoop = useSelector(selectAuthorLoop)
  const { error: toastError } = useToast()
  const { data: sceneImages } = useAuthorSceneImages(novelId, chapter)
  const sceneFailure = useSelector(selectAuthorSceneImageLastFailure)
  useEffect(() => {
    if (!sceneFailure) return
    // Always consume, so a failure from a chapter we're not showing can't surface as a stale
    // toast later; only the viewed chapter's failure is worth interrupting the user for (the
    // row itself keeps the inline red hint either way).
    if (sceneFailure.chapter === chapter) toastError(`场景生图失败：${sceneFailure.error}`)
    dispatch(authorSceneImageFailureConsumed())
  }, [sceneFailure, chapter, dispatch, toastError])
  const handleGenerateScene = (index: number) => {
    void requestAuthorSceneImage(chapter, index).then((res) => {
      if (!res.ok) toastError('场景生图请求失败，请重试')
    })
  }
  const resumable = useSelector((s: RootState) => selectResumable(chapter)(s))
  const disabled = useSelector(selectBusy)
  const onRun = (ch: number) => { void dispatch(startAuthorLoop(ch)) }
  const onResume = (ch: number) => { void dispatch(resumeAuthorLoop(ch)) }
  const onRestart = (ch: number) => { void dispatch(restartAuthorLoop(ch)) }
  const onSelectChapter = (ch: number) => dispatch(setChapterAction(ch))
  const onStop = () => { void dispatch(stopAuthorLoop()) }

  const [selected, setSelected] = useState(chapter)
  useEffect(() => { setSelected(chapter) }, [chapter])

  const running = authorLoop.status === 'running'
  //Segment products are now divided into beats, segment information = each beat. Progress is aggregated by "segment":
  const segMsgs = authorLoop.messages.filter(
    (m): m is Extract<AuthorMessage, { type: 'segment' }> => m.type === 'segment',
  )
  const segDone = new Set(segMsgs.map(m => m.segment.index)).size  //Number of segments involved (duplication index)
  const cur = segMsgs.length ? segMsgs[segMsgs.length - 1].segment : null  //Current paragraph/section
  //Heartbeat agent → human reading stage label (let the "writing" bubble show what the backend is doing currently).
  const pAgent = authorLoop.progress?.agent ?? ''
  const phaseLabel = !pAgent ? null
    : pAgent.startsWith('decide') ? '构思方案'
    : pAgent.startsWith('write') ? '落字润色'
    : pAgent.startsWith('summary') ? '整理摘要'
    : '处理中'
  const canRun = selected >= 1 && !running && !disabled
  const showResume = resumable && !running && selected >= 1 && !disabled

  //Tag filtering: Hide collection (empty = show all). The filter bar is only shown in conversation mode (there are tagged messages/live).
  const [hiddenCats, setHiddenCats] = useState<Set<AuthorFilterCat>>(new Set())
  const presentCats = new Set<AuthorFilterCat>()
  authorLoop.messages.forEach(m => { const c = messageCategory(m); if (c) presentCats.add(c) })
  ;(authorLoop.live ?? []).forEach(lv => { const c = liveCategory(lv.agent); if (c) presentCats.add(c) })
  const toggleCat = (c: AuthorFilterCat) => setHiddenCats(prev => {
    const next = new Set(prev)
    if (next.has(c)) next.delete(c)
    else next.add(c)
    return next
  })

  //New bubble/text increment → only follow the scroll to the bottom when the user is already near the bottom (to avoid being dragged away when looking back)
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)
  const NEAR_BOTTOM_PX = 96

  const isNearBottom = (el: HTMLElement) =>
    el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    stickToBottomRef.current = isNearBottom(el)
  }

  useEffect(() => { stickToBottomRef.current = true }, [chapter])

  const lastMsg = authorLoop.messages[authorLoop.messages.length - 1]
  const lastMsgToken = lastMsg
    ? lastMsg.type === 'segment'
      ? `${lastMsg.id}:${lastMsg.segment.text.length}`
      : lastMsg.id
    : ''
  const liveToken = (authorLoop.live ?? []).reduce((n, lv) => n + lv.text.length, 0)
  const scrollTrigger = `${authorLoop.messages.length}|${lastMsgToken}|${(authorLoop.live ?? []).length}:${liveToken}`

  useEffect(() => {
    if (!stickToBottomRef.current) return
    const el = scrollRef.current
    if (!el) return
    if (typeof el.scrollTo === 'function') {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    } else {
      el.scrollTop = el.scrollHeight
    }
  }, [scrollTrigger])

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/*head + trigger*/}
      <PageHeader
        icon={<PenLine size={18} className="text-[var(--c-tag-violet-text)]" />}
        title="主笔逐段写作"
        subtitle="逐段对话：主笔写一段 → 你选方案 / 满意或重写 → 续写下一段。"
        actions={
          <>
            <Select
              value={String(selected)}
              onValueChange={(v) => {
                const n = Number(v)
                setSelected(n)
                onSelectChapter(n)
              }}
              disabled={running || chapters.length === 0}
            >
              <SelectTrigger className="w-24">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {chapters.map(ch => <SelectItem key={ch} value={String(ch)}>第{ch}章</SelectItem>)}
              </SelectContent>
            </Select>
            {running ? (
              <Button
                type="button"
                variant="destructive"
                onClick={onStop}
                title="中途停止写作（已写段保留，可重来）"
              >
                <Square size={14} />停止
              </Button>
            ) : showResume ? (
              <>
                <Button
                  type="button"
                  variant="default"
                  onClick={() => onResume?.(selected)}
                >
                  <Play size={14} />继续
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => onRestart?.(selected)}
                >
                  <RotateCcw size={14} />重新开始
                </Button>
              </>
            ) : (
              <Button
                type="button"
                variant="default"
                onClick={() => onRun(selected)}
                disabled={!canRun}
              >
                <Play size={14} />运行主笔
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              onClick={() => navigate(`/novel/${novelId}/manuscript`)}
              title={VIEW_LABELS.manuscript}
              aria-label={VIEW_LABELS.manuscript}
            >
              <FileText size={14} />{VIEW_LABELS.manuscript}
            </Button>
          </>
        }
      />

      <div className="flex-1 flex min-h-0 overflow-hidden">
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
      {/*The total progress bar of the entire chapter: beat level done/total, letting the user know where the creation is*/}
      {authorLoop.chapterProgress && authorLoop.chapterProgress.total > 0 && (() => {
        const { done, total } = authorLoop.chapterProgress!
        const pct = Math.min(100, Math.round((done / total) * 100))
        return (
          <div className="px-4 py-2 border-b border-[var(--c-border-subtle)] bg-[var(--c-surface)]">
            <div className="flex items-center justify-between text-xs text-[var(--c-text-muted)] mb-1">
              <span>第{authorLoop.chapter || selected}章 创作进度</span>
              <span className="tabular-nums">{done}/{total} 段 · {pct}%</span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-[var(--c-surface-muted)] overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-300 ${authorLoop.status === 'done' ? 'bg-emerald-500' : 'bg-[var(--c-accent)]'}`}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )
      })()}

      {/*Tag filter bar: Show or hide by agent category (only appears when there are tags in conversation mode)*/}
      {presentCats.size > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap px-4 py-2 border-b border-[var(--c-border-subtle)] bg-[var(--c-surface)]">
          <span className="text-xs text-[var(--c-text-faint)] mr-1">标签：</span>
          {FILTER_CATS.filter(c => presentCats.has(c.cat)).map(c => {
            const on = !hiddenCats.has(c.cat)
            return (
              <button
                key={c.cat}
                onClick={() => toggleCat(c.cat)}
                aria-pressed={on}
                className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                  on ? `${c.chip} border-transparent` : 'bg-slate-50 text-slate-400 border-slate-200 line-through'
                }`}
              >
                {c.label}
              </button>
            )
          })}
        </div>
      )}

      {/*conversation flow*/}
      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-3xl mx-auto space-y-4">
          {authorLoop.status === 'idle' && !showResume && (
            <div className="text-center text-sm text-slate-400 py-16">
              选择章节后点击「运行主笔」开始逐段对话写作。
            </div>
          )}
          {authorLoop.status === 'idle' && showResume && authorLoop.messages.length === 0 && (
            <div className="text-center text-sm text-slate-400 py-16">
              本章有未完成的写作进度，可点「继续」续跑或「重新开始」清空重来。
            </div>
          )}

          {/*Conversation timeline (saved throughout): paragraph/status/summary (all left agent bubbles)*/}
          {buildAuthorTimelineItems(authorLoop.messages).map(item => {
            if (item.kind === 'context') {
              if (hiddenCats.has('state')) return null
              return <AuthorContextBubble key={`ctx-${item.group.segIndex}`} group={item.group} />
            }
            const m = item.message
            const cat = messageCategory(m)
            if (cat && hiddenCats.has(cat)) return null
            if (m.type === 'segment') return (
              <SegmentBubble
                key={m.id}
                seg={m.segment}
                chapter={chapter}
                sceneImageUrl={sceneImages?.[String(m.segment.index)]}
                onGenerateSceneImage={() => handleGenerateScene(m.segment.index)}
              />
            )
            if (m.type === 'summary') return <SummaryBubble key={m.id} text={m.text} />
            if (m.type === 'state') {
              return <AuthorContextBubble key={m.id} group={{ segIndex: -999, anchorIdx: item.messageIdx, state: m }} />
            }
            if (m.type === 'event_log') {
              const entries = m.events.filter((e) => e.summary)
              if (!entries.length) return null
              return (
                <AgentBubble key={m.id}>
                  <EventLogBubble entries={entries} />
                </AgentBubble>
              )
            }
            if (m.type === 'recall') {
              return (
                <AgentBubble key={m.id}>
                  <RecallContextBubble recallContext={m.recallContext} />
                </AgentBubble>
              )
            }
            return null
          })}

          {/*Streaming live: The visible content generated by each agent of this beat coexists (narration/lines/synthesis), and is replaced by segment after finalization*/}
          {(authorLoop.live ?? []).map((lv, i) => {
            const cat = liveCategory(lv.agent)
            if (cat && hiddenCats.has(cat)) return null
            if (!lv.text) return null
            const charPerf = lv.agent === 'character' ? parseCharacterPerformance(lv.text) : null
            const liveText = lv.agent === 'synthesis' ? stripSynthesisProse(lv.text) : lv.text
            if (!liveText && !charPerf) return null
            const styleRewriteChip = authorLoop.styleRewriting?.agent === lv.agent && authorLoop.styleRewriting.role === lv.role ? (
              <span className="ml-1 inline-block text-xs text-amber-600 animate-pulse">
                检测到 AI 味文本，正在重写…
              </span>
            ) : null
            return (
              <AgentBubble key={`live-${i}-${lv.agent}-${lv.role ?? ''}`}>
                <span className={`inline-block text-xs px-2 py-0.5 rounded-full mb-1.5 ${AGENT_CHIP[lv.agent] ?? 'bg-slate-100 text-slate-600'}`}>
                  {agentLabel(lv.agent, lv.role) || '生成中'} ✍️
                </span>
                {charPerf ? (
                  <>
                    <CharacterPerformanceFields
                      text={charPerf.dialogue}
                      intent={charPerf.intent}
                      psychology={charPerf.psychology}
                      folded={false}
                      expanded
                      onToggle={() => {}}
                    />
                    {styleRewriteChip}
                  </>
                ) : (
                  <div className="text-sm text-slate-700 whitespace-pre-wrap leading-relaxed">
                    {liveText}
                    {styleRewriteChip}
                  </div>
                )}
              </AgentBubble>
            )
          })}

          {/*Running → Writing indication (including real-time heartbeat + suspected stuck soft alarm)*/}
          {running && (
            <AgentBubble>
              <div className="flex flex-col gap-1">
                <span className="flex items-center gap-2 text-sm text-[var(--c-accent)]">
                  <Loader2 size={14} className="animate-spin" />
                  主笔写作中…（
                  {cur
                    ? <>第 {cur.index + 1} 段{(cur.beats ?? 1) > 1 ? ` · 第 ${(cur.beat ?? 0) + 1}/${cur.beats} 节` : ''}</>
                    : '准备中'}
                  {authorLoop.total > 0 ? ` ／ 共 ${authorLoop.total} 段` : ''}
                  {phaseLabel ? ` · ${phaseLabel}` : ''}
                  {(authorLoop.progress?.attempts ?? 1) > 1
                    ? `（重试 ${authorLoop.progress?.attempt}/${authorLoop.progress?.attempts}）`
                    : ''}
                  ）
                </span>
                {authorLoop.stalled && (
                  <span className="flex items-center gap-1.5 text-xs text-amber-600">
                    <AlertTriangle size={12} />
                    响应较慢、疑似卡住——仍在等待后端，若长时间无进展可点「停止」后重跑。
                  </span>
                )}
              </div>
            </AgentBubble>
          )}

          {authorLoop.status === 'done' && (
            <div className="flex items-center justify-center gap-2 text-sm text-emerald-600 font-medium py-3">
              <CheckCircle2 size={15} />第{chapter}章 写作完成（共 {authorLoop.total || segDone} 段）
            </div>
          )}
          {authorLoop.status === 'error' && (
            <div className="flex items-center justify-center gap-2 text-sm text-red-600 font-medium py-3">
              <AlertTriangle size={15} />{authorLoop.error ?? '主笔写作失败'}
            </div>
          )}
        </div>
      </div>
      </div>
      {selected >= 1 && <AuthorCharacterPanel chapter={selected} />}
      </div>
    </div>
  )
}
