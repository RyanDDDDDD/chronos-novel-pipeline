import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Flag, Globe, Layers, MapPin, Users, Zap, BookOpen, Palette, ScrollText, type LucideIcon } from 'lucide-react'
import CharacterArchivePage from '@/features/archives/components/CharacterArchivePage'
import AttachmentsTab from '@/features/setup/components/AttachmentsTab'
import { detectRecognizedNames } from '@/shared/components/mention/mentionCandidates'
import { useCast, usePlot, useWorld } from '@/shared/queries/setup'
import PlotChapterSummaryCard from '@/features/setup/components/PlotChapterSummaryCard'
import CastTab from '@/features/setup/components/CastTab'
import {
  EditableInputField,
  EditableTextField,
  useFieldSaveState,
  SaveStatusDot,
} from '@/features/setup/components/setupFieldEditors'
import { patchWorldField, patchPlotChapterMeta } from '@/shared/utils/setup'
import { useChapterSkeleton } from '@/features/setup/queries/skeleton'
import { computeSkeletonCharCounts, patchSkeletonStage, type SkeletonBeat } from '@/features/setup/utils/skeleton'
import AutoGrowTextarea from '@/shared/components/AutoGrowTextarea'
import EmptyStateCard from '@/shared/components/EmptyStateCard'
import PageHeader from '@/shared/components/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/shared/components/ui/accordion'
import { useToast } from '@/shared/hooks/useToast'
import type { SetupTab } from '@/shared/utils/novelRoute'

import type { WorldNamedItem } from '@/shared/types'

interface SetupPageProps {
  tab: SetupTab
}

export default function SetupPage({ tab }: SetupPageProps) {
  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden bg-app">
      <PageHeader title="设定" subtitle="世界观、人物与剧情设定，随时编辑保存" />
      {tab === 'archives' ? (
        <CharacterArchivePage embedded />
      ) : tab === 'attachments' ? (
        <div className="flex flex-1 min-h-0 flex-col overflow-hidden p-4 pt-4">
          <AttachmentsTab />
        </div>
      ) : (
      <div className="flex-1 min-h-0 overflow-y-auto p-4 pt-4 space-y-4">
      {tab === 'world' && (
        <WorldTab />
      )}
      {tab === 'cast' && (
        <CastTab />
      )}
      {tab === 'plot' && (
        <PlotTab />
      )}
      </div>
      )}
    </div>
  )
}

const WORLD_SCALAR_SECTIONS: {
  key: 'tone' | 'background'
  label: string
  icon: LucideIcon
}[] = [
  { key: 'tone', label: '基调', icon: Palette },
  { key: 'background', label: '背景', icon: ScrollText },
]

const WORLD_ENTITY_SECTIONS: {
  key: 'factions' | 'geography' | 'races' | 'power_system' | 'core_themes'
  label: string
  icon: LucideIcon
}[] = [
  { key: 'factions', label: '势力', icon: Flag },
  { key: 'geography', label: '地理', icon: MapPin },
  { key: 'races', label: '种族', icon: Users },
  { key: 'power_system', label: '力量体系', icon: Zap },
  { key: 'core_themes', label: '核心主题', icon: Layers },
]

function WorldScalarFieldCard({
  label,
  icon: Icon,
  value,
  onSave,
}: {
  label: string
  icon: LucideIcon
  value: string
  onSave: (next: string) => Promise<{ ok: true } | { ok: false; error: string }>
}) {
  return (
    <section className="border border-slate-200 rounded-lg bg-white overflow-hidden">
      <header className="flex items-center gap-2 px-3.5 py-2.5 border-b border-slate-100 bg-slate-50/80">
        <Icon size={15} className="text-[var(--c-tag-violet-text)] shrink-0" aria-hidden />
        <h3 className="text-sm font-semibold text-slate-800">{label}</h3>
      </header>
      <div className="p-3.5">
        <EditableTextField label="" value={value} onSave={onSave} />
      </div>
    </section>
  )
}

function KeywordsEditor({
  keywords,
  onChange,
}: {
  keywords: string[]
  onChange: (next: string[]) => void
}) {
  const [draft, setDraft] = useState('')
  return (
    <div>
      <div className="text-xs text-slate-400 mb-1">触发关键词</div>
      <div className="flex flex-wrap gap-1.5 items-center">
        {keywords.map((k, i) => (
          <span key={i} className="px-2 py-0.5 rounded-full bg-slate-100 text-xs text-slate-600 flex items-center gap-1">
            {k}
            <Button type="button" variant="ghost" size="icon-xs" onClick={() => onChange(keywords.filter((_, j) => j !== i))} aria-label={`删除${k}`} className="h-auto w-auto p-0">✕</Button>
          </span>
        ))}
        <Input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && draft.trim()) { onChange([...keywords, draft.trim()]); setDraft('') }
          }}
          placeholder="回车新增"
          className="rounded-full w-20 h-auto text-xs px-2 py-1"
        />
      </div>
    </div>
  )
}

function WorldEntitySection({
  fieldKey,
  label,
  icon: Icon,
  items,
  onSaveItems,
}: {
  fieldKey: string
  label: string
  icon: LucideIcon
  items: WorldNamedItem[]
  onSaveItems: (field: string, items: WorldNamedItem[]) => Promise<{ ok: true } | { ok: false; error: string }>
}) {
  const [local, setLocal] = useState(items)
  useEffect(() => setLocal(items), [items])
  const { state, setState, error, setError } = useFieldSaveState()
  const { confirm } = useToast()
  // Only power_system/core_themes entries are actually consumed by the recall keyword gate
  // (see engine/memory_recall/recall.py) -- hide the editor for factions/geography/races so it
  // doesn't invite filling in a field that's silently ignored there.
  const showKeywords = fieldKey === 'power_system' || fieldKey === 'core_themes'

  const persist = async (next: WorldNamedItem[]) => {
    setLocal(next)
    setState('saving')
    const res = await onSaveItems(fieldKey, next)
    if (res.ok) {
      setState('saved')
      setError('')
    } else {
      setState('error')
      setError(res.error)
    }
  }

  const updateLocal = (i: number, patch: Partial<WorldNamedItem>) => {
    setLocal((prev) => prev.map((it, j) => (j === i ? { ...it, ...patch } : it)))
  }
  const commit = () => {
    void persist(local)
  }
  const removeItem = async (i: number) => {
    if (!(await confirm(`删除「${local[i].name || '（未命名）'}」？`))) return
    void persist(local.filter((_, j) => j !== i))
  }
  const addItem = () => {
    void persist([...local, { name: '', desc: '' }])
  }
  const setKeywords = (i: number, next: string[]) => {
    void persist(local.map((it, j) => (j === i ? { ...it, keywords: next } : it)))
  }

  return (
    <section className="border border-slate-200 rounded-lg bg-white overflow-hidden">
      <header className="flex items-center gap-2 px-3.5 py-2.5 border-b border-slate-100 bg-slate-50/80">
        <Icon size={15} className="text-[var(--c-tag-violet-text)] shrink-0" aria-hidden />
        <h3 className="text-sm font-semibold text-slate-800">{label}</h3>
        <SaveStatusDot state={state} error={error} />
        <span className="ml-auto text-xs text-slate-400 tabular-nums">{local.length}</span>
        <Button
          type="button"
          variant="outline"
          onClick={addItem}
          className="text-xs px-2 py-1 h-auto rounded-lg border-[var(--c-tag-violet-border)] text-[var(--c-accent)] hover:bg-[var(--c-accent-subtle)]"
        >
          + 新增
        </Button>
      </header>
      <div className="p-3 grid grid-cols-1 md:grid-cols-2 gap-2">
        {local.map((it, i) => (
          <article key={i} className="rounded-lg border border-slate-100 bg-slate-50/50 p-2.5 space-y-1.5">
            <div className="flex items-center gap-2">
              <Input
                value={it.name}
                onChange={(e) => updateLocal(i, { name: e.target.value })}
                onBlur={commit}
                placeholder="名称"
                className="flex-1 text-sm font-medium border-transparent focus:border-[var(--c-border)]"
              />
              <Button
                type="button"
                variant="ghost"
                onClick={() => void removeItem(i)}
                aria-label={`删除${it.name || '该条目'}`}
                className="text-xs text-rose-500 hover:text-rose-700 px-1.5 h-auto"
              >
                ✕
              </Button>
            </div>
            <AutoGrowTextarea
              value={it.desc}
              onChange={(e) => updateLocal(i, { desc: e.target.value })}
              onBlur={commit}
              rows={2}
              minPx={58}
              maxPx={400}
              placeholder="描述"
              className="w-full text-sm text-slate-600 leading-relaxed px-2 py-1 rounded border border-slate-200 focus:outline-none focus:ring-2 focus:ring-[var(--c-focus-ring)] resize-none"
            />
            {showKeywords && (
              <KeywordsEditor keywords={it.keywords ?? []} onChange={(next) => setKeywords(i, next)} />
            )}
          </article>
        ))}
      </div>
    </section>
  )
}

function WorldTab() {
  const queryClient = useQueryClient()
  const { data } = useWorld()
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: ['setup', 'world'] })
  }, [queryClient])
  const wb = data?.world_bible
  const scalarSections = wb
    ? WORLD_SCALAR_SECTIONS.flatMap(({ key, label, icon }) =>
        wb[key] !== undefined ? [{ key, label, icon, content: wb[key] ?? '' }] : [],
      )
    : []
  const entitySections = wb
    ? WORLD_ENTITY_SECTIONS.flatMap(({ key, label, icon }) => {
        const items = wb[key]
        // Array.isArray guards against a not-yet-migrated novel where this field is still a
        // legacy shape (power_system as a free-text string) -- rendering nothing for it here is
        // safer than crashing WorldEntitySection's `.map()` on a non-array value.
        return Array.isArray(items) ? [{ key, label, icon, items }] : []
      })
    : []

  const saveField = async (field: string, value: unknown) => {
    const res = await patchWorldField(field, value)
    if (res.ok) void queryClient.invalidateQueries({ queryKey: ['setup', 'world'] })
    return res
  }

  return (
    <div className="space-y-4 max-w-5xl mx-auto">
      {!wb && (
        <EmptyStateCard icon={Globe} message="尚未生成世界设定，去「对话」页让共创者构建，或在此手动填写。" />
      )}
      {wb && (
        <div className="space-y-4">
          {scalarSections.map((s) => (
            <WorldScalarFieldCard
              key={s.key}
              label={s.label}
              icon={s.icon}
              value={s.content}
              onSave={(v) => saveField(s.key, v)}
            />
          ))}
          {entitySections.map((s) => (
            <WorldEntitySection
              key={s.key}
              fieldKey={s.key}
              label={s.label}
              icon={s.icon}
              items={s.items}
              onSaveItems={saveField}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function PlotTab() {
  const queryClient = useQueryClient()
  const { confirm } = useToast()
  const { data: chapters = [] } = usePlot()
  const { data: cast = [] } = useCast()
  const chapterNums = chapters.map((c) => c.chapter).filter((n) => typeof n === 'number')
  const titleByChapter = Object.fromEntries(chapters.map((c) => [c.chapter, c.title ?? '']))
  const coreXpByChapter = Object.fromEntries(chapters.map((c) => [c.chapter, c.core_xp ?? []]))
  const [selected, setSelected] = useState<number | null>(null)
  useEffect(() => {
    setSelected((prev) => (prev != null && chapterNums.includes(prev) ? prev : chapterNums[0] ?? null))
  }, [chapters])
  const { data } = useChapterSkeleton(selected)
  const charCounts = useMemo(
    () => (data?.stages ? computeSkeletonCharCounts(data.stages) : null),
    [data?.stages],
  )
  const stageCountByNum = useMemo(
    () => Object.fromEntries(charCounts?.stages.map((s) => [s.stage_num, s]) ?? []),
    [charCounts],
  )
  const characterNames = useMemo(
    () => cast.map((c) => c.name).filter((name) => name.length > 0),
    [cast],
  )
  const chapterOutlineText = useMemo(
    () => (data?.stages ?? []).map((s) => s.description ?? '').join('\n'),
    [data?.stages],
  )
  const recognizedCharacters = useMemo(
    () => detectRecognizedNames(chapterOutlineText, characterNames),
    [chapterOutlineText, characterNames],
  )

  const invalidatePlot = () => {
    void queryClient.invalidateQueries({ queryKey: ['setup', 'plot'] })
    if (selected != null) void queryClient.invalidateQueries({ queryKey: ['skeleton'] })
  }

  const saveTitle = async (v: string) => {
    if (selected == null) return { ok: false as const, error: '未选中章节' }
    const res = await patchPlotChapterMeta(selected, { title: v })
    if (res.ok) invalidatePlot()
    return res
  }

  const saveStageDescription = async (
    stageNum: number, v: string, hasBeats: boolean,
  ): Promise<{ ok: true } | { ok: false; error: string }> => {
    if (selected == null) return { ok: false, error: '未选中章节' }
    if (hasBeats && !(await confirm('修改粗大纲会清空本段已扩写的分拍底稿，确定吗？'))) {
      return { ok: false, error: '已取消' }
    }
    const res = await patchSkeletonStage(selected, { op: 'replace', stage_num: stageNum, fields: { description: v } })
    if (res.ok) invalidatePlot()
    return res
  }

  const saveStageTitle = async (
    stageNum: number, v: string,
  ): Promise<{ ok: true } | { ok: false; error: string }> => {
    if (selected == null) return { ok: false, error: '未选中章节' }
    const res = await patchSkeletonStage(selected, { op: 'replace', stage_num: stageNum, fields: { title: v } })
    if (res.ok) invalidatePlot()
    return res
  }

  const saveStageLocation = async (
    stageNum: number, v: string,
  ): Promise<{ ok: true } | { ok: false; error: string }> => {
    if (selected == null) return { ok: false, error: '未选中章节' }
    const res = await patchSkeletonStage(selected, { op: 'replace', stage_num: stageNum, fields: { location: v } })
    if (res.ok) invalidatePlot()
    return res
  }

  const saveBeatText = async (
    stageNum: number, beatIdx: number, v: string, beat: SkeletonBeat,
  ): Promise<{ ok: true } | { ok: false; error: string }> => {
    if (selected == null) return { ok: false, error: '未选中章节' }
    const res = await patchSkeletonStage(selected, {
      op: 'replace_beat', stage_num: stageNum, beat_idx: beatIdx,
      beat: { text: v, sensation_notes: beat.sensation_notes, dialogue_draft: beat.dialogue_draft },
    })
    if (res.ok) invalidatePlot()
    return res
  }

  const saveBeatDialogueDraft = async (
    stageNum: number, beatIdx: number, v: string,
  ): Promise<{ ok: true } | { ok: false; error: string }> => {
    if (selected == null) return { ok: false, error: '未选中章节' }
    const res = await patchSkeletonStage(selected, {
      op: 'set_beat_dialogue', stage_num: stageNum, beat_idx: beatIdx, dialogue_draft: v,
    })
    if (res.ok) invalidatePlot()
    return res
  }

  return (
    <div className="space-y-3">
      {chapterNums.length === 0 && (
        <EmptyStateCard icon={BookOpen} message="尚未生成剧情，先去「对话」页建剧情。" />
      )}
      {chapterNums.length > 0 && (
        <div className="flex items-center gap-2">
          <Label htmlFor="skeleton-chapter" className="text-xs text-[color:var(--c-text-secondary)] shrink-0">章节</Label>
          <Select value={selected != null ? String(selected) : ''} onValueChange={(v) => setSelected(Number(v))}>
            <SelectTrigger id="skeleton-chapter" className="w-auto min-w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {chapterNums.map((ch) => (
                <SelectItem key={ch} value={String(ch)}>
                  第{ch}章
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      {selected != null && (
        <EditableInputField
          label="章标题"
          value={titleByChapter[selected] ?? ''}
          onSave={saveTitle}
        />
      )}
      {selected != null && (
        <PlotChapterSummaryCard
          coreXp={coreXpByChapter[selected] ?? []}
          charCounts={charCounts}
          recognizedCharacters={recognizedCharacters}
          hasOutlineText={chapterOutlineText.trim().length > 0}
        />
      )}
      <Accordion type="multiple" className="space-y-3">
        {data?.stages?.map((s) => {
          const sc = stageCountByNum[s.stage_num]
          return (
          <AccordionItem key={s.stage_num} value={String(s.stage_num)} className="border border-[var(--c-border)] rounded-lg bg-[var(--c-surface)] text-sm">
            <AccordionTrigger className="p-3">
              <div className="flex items-center gap-2 flex-1">
                <h3 className="font-semibold text-[var(--c-text)]">
                  Stage {s.stage_num}{s.title ? `：${s.title}` : ''}
                </h3>
                <span className={`text-xs px-2 py-0.5 rounded-full ${s.expanded ? 'bg-emerald-100 text-emerald-700' : 'bg-[var(--c-surface-muted)] text-[var(--c-text-muted)]'}`}>
                  {s.expanded ? '已扩写' : '待扩写'}
                </span>
                {sc && (
                  <span className="text-xs text-[var(--c-text-muted)] tabular-nums shrink-0 ml-auto">
                    粗大纲 {sc.outline.toLocaleString('zh-CN')} · 底稿 {sc.beats.toLocaleString('zh-CN')}
                  </span>
                )}
              </div>
            </AccordionTrigger>
            <AccordionContent className="px-3 pb-3 space-y-2">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              <EditableInputField
                label="场景标题"
                value={s.title || ''}
                onSave={(v) => saveStageTitle(s.stage_num, v)}
              />
              <EditableInputField
                label="地点"
                value={s.location || ''}
                onSave={(v) => saveStageLocation(s.stage_num, v)}
              />
            </div>
            <EditableTextField
              label={`粗大纲${sc != null ? `（${sc.outline.toLocaleString('zh-CN')} 字）` : ''}`}
              value={s.description || ''}
              onSave={(v) => saveStageDescription(s.stage_num, v, s.beats.length > 0)}
              rows={2}
            />
            <div>
              <Label className="text-xs font-medium text-[var(--c-text-muted)] mb-0.5 block">
                分拍底稿
                {sc != null && <span className="ml-1 tabular-nums font-normal">({sc.beats.toLocaleString('zh-CN')} 字)</span>}
              </Label>
              {s.beats.length > 0 ? (
                <div className="space-y-2">
                  {s.beats.map((b, i) => (
                    <div key={i} className="border-l-2 border-[var(--c-tag-violet-border)] pl-2">
                      <Label className="text-xs text-[var(--c-text-muted)] mb-0.5 block">拍 {i}</Label>
                      <EditableTextField
                        label=""
                        value={b.text}
                        onSave={(v) => saveBeatText(s.stage_num, i, v, b)}
                        rows={3}
                      />
                      <div className="mt-1.5 border-l-2 border-amber-200 pl-2">
                        <Label className="text-xs font-medium text-amber-600 mb-0.5 block">台词草稿</Label>
                        {!b.dialogue_draft && (
                          <p className="text-xs text-[var(--c-text-muted)] italic mb-1">（这拍判断不需要设计台词）</p>
                        )}
                        <EditableTextField
                          label=""
                          value={b.dialogue_draft || ''}
                          onSave={(v) => saveBeatDialogueDraft(s.stage_num, i, v)}
                          rows={2}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[var(--c-text-muted)] italic">尚未扩写——去「对话」页扩写本章骨架。</p>
              )}
            </div>
            </AccordionContent>
          </AccordionItem>
          )
        })}
      </Accordion>
      {data && data.stages.length === 0 && (
        <EmptyStateCard icon={BookOpen} message={`第${selected}章无 stage。`} />
      )}
    </div>
  )
}

