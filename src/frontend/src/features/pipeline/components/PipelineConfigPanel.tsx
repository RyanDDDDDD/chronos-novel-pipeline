import { useRef, useState } from 'react'
import { useAuthorLoopDialogueConfig, useSetAuthorLoopDialogueConfig } from '@/features/pipeline/queries/authorLoopDialogue'
import ReviewHookGroupSection from '@/features/pipeline/components/ReviewHookGroupSection'
import { useChronosConfig, usePatchNovelImportConfig } from '@/shared/queries/chronosConfig'
import {
  clampInt,
  NOVEL_IMPORT_DEFAULTS,
  resolveNovelImport,
} from '@/shared/utils/chronosConfig'
import PipelineSidePanel, {
  PipelineConfigSection,
  pipelinePanelHintClass,
  pipelinePanelCountInputClass,
  pipelinePanelWideCountInputClass,
} from '@/features/pipeline/components/PipelineSidePanel'
import { Textarea } from '@/shared/components/ui/textarea'
import { Button } from '@/shared/components/ui/button'

const rangeClass =
  'w-full h-1.5 accent-[var(--c-accent)] cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed'
const MIN_TARGET_WORDS = 1500
const MAX_TARGET_WORDS = 100_000
const MIN_CHARACTER_COUNT = 1
const MAX_CHARACTER_COUNT = 30
const MIN_CHAPTER_COUNT = 1
const MAX_CHAPTER_COUNT = 100

function clampTargetWords(value: number): number {
  return Math.min(MAX_TARGET_WORDS, Math.max(MIN_TARGET_WORDS, value))
}

function parseTargetWordsInput(raw: string): number | null {
  const digits = raw.replace(/\D/g, '')
  if (!digits) return null
  const n = Number(digits)
  return Number.isFinite(n) ? n : null
}

function clampCount(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function parseCountInput(raw: string): number | null {
  const digits = raw.replace(/\D/g, '')
  if (!digits) return null
  const n = Number(digits)
  return Number.isFinite(n) ? n : null
}

export default function PipelineConfigPanel({
  novelId, onSelectNode,
}: { novelId: string; onSelectNode: (id: string) => void }) {
  const save = useSetAuthorLoopDialogueConfig(novelId)
  const { data: cfg } = useAuthorLoopDialogueConfig(novelId)
  const patchNovelImport = usePatchNovelImportConfig()
  const { data: chronosCfg } = useChronosConfig()
  const novelImport = resolveNovelImport(chronosCfg)
  const [identityDraft, setIdentityDraft] = useState<string | null>(null)
  const lastCommittedIdentityRef = useRef<string | null>(null)
  const defaultIdentity = cfg?.default_identity ?? ''
  const identity = identityDraft ?? (cfg?.config.chat_identity || defaultIdentity)
  const hasIdentityOverride = (identityDraft ?? cfg?.config.chat_identity ?? '').trim() !== ''

  const commitIdentity = (value: string) => {
    const trimmed = value.trim()
    const baseline = lastCommittedIdentityRef.current ?? (cfg?.config.chat_identity || defaultIdentity)
    setIdentityDraft(trimmed)
    if (trimmed === baseline.trim()) return
    lastCommittedIdentityRef.current = trimmed
    save.mutate({ dialogue: { chat_identity: trimmed } })
  }

  const [targetWordsOverride, setTargetWordsOverride] = useState<number | null>(null)
  const [wordsDraft, setWordsDraft] = useState<string | null>(null)
  const targetWords = targetWordsOverride ?? cfg?.config.target_words ?? 3000

  const setTargetWordsLocal = (value: number) => {
    setTargetWordsOverride(clampTargetWords(value))
    setWordsDraft(null)
  }

  const persistTargetWords = (value: number) => {
    const next = clampTargetWords(value)
    setTargetWordsOverride(next)
    setWordsDraft(null)
    save.mutate({ dialogue: { target_words: next } })
  }

  const commitTargetWords = (value: number) => {
    persistTargetWords(value)
  }

  const commitWordsInput = () => {
    const parsed = parseTargetWordsInput(wordsDraft ?? '')
    setWordsDraft(null)
    if (parsed == null) return
    commitTargetWords(parsed)
  }

  const [characterCountOverride, setCharacterCountOverride] = useState<number | null>(null)
  const [characterCountDraft, setCharacterCountDraft] = useState<string | null>(null)
  const characterCount = characterCountOverride ?? cfg?.config.auto_build_character_count ?? 5

  const commitCharacterCount = (value: number) => {
    const next = clampCount(value, MIN_CHARACTER_COUNT, MAX_CHARACTER_COUNT)
    setCharacterCountOverride(next)
    setCharacterCountDraft(null)
    save.mutate({ dialogue: { auto_build_character_count: next } })
  }

  const commitCharacterCountInput = () => {
    const parsed = parseCountInput(characterCountDraft ?? '')
    setCharacterCountDraft(null)
    if (parsed == null) return
    commitCharacterCount(parsed)
  }

  const [chapterCountOverride, setChapterCountOverride] = useState<number | null>(null)
  const [chapterCountDraft, setChapterCountDraft] = useState<string | null>(null)
  const chapterCount = chapterCountOverride ?? cfg?.config.auto_build_chapter_count ?? 3

  const commitChapterCount = (value: number) => {
    const next = clampCount(value, MIN_CHAPTER_COUNT, MAX_CHAPTER_COUNT)
    setChapterCountOverride(next)
    setChapterCountDraft(null)
    save.mutate({ dialogue: { auto_build_chapter_count: next } })
  }

  const commitChapterCountInput = () => {
    const parsed = parseCountInput(chapterCountDraft ?? '')
    setChapterCountDraft(null)
    if (parsed == null) return
    commitChapterCount(parsed)
  }

  const [chunkSizeDraft, setChunkSizeDraft] = useState<string | null>(null)
  const commitChunkSize = (raw: string) => {
    setChunkSizeDraft(null)
    const next = clampInt(raw, NOVEL_IMPORT_DEFAULTS.chunk_size)
    if (next === novelImport.chunk_size) return
    patchNovelImport.mutate({ chunk_size: next })
  }

  const [compactionDraft, setCompactionDraft] = useState<string | null>(null)
  const commitCompactionInterval = (raw: string) => {
    setCompactionDraft(null)
    const next = clampInt(raw, NOVEL_IMPORT_DEFAULTS.compaction_interval)
    if (next === novelImport.compaction_interval) return
    patchNovelImport.mutate({ compaction_interval: next })
  }

  const [concurrencyDraft, setConcurrencyDraft] = useState<string | null>(null)
  const commitConcurrency = (raw: string) => {
    setConcurrencyDraft(null)
    const trimmed = raw.trim()
    const next = trimmed === '' ? null : clampInt(trimmed, 0)
    if (next === novelImport.concurrency) return
    patchNovelImport.mutate({ concurrency: next })
  }

  const [warnThresholdDraft, setWarnThresholdDraft] = useState<string | null>(null)
  const commitWarnThreshold = (raw: string) => {
    setWarnThresholdDraft(null)
    const next = clampInt(raw, NOVEL_IMPORT_DEFAULTS.warn_threshold_chars)
    if (next === novelImport.warn_threshold_chars) return
    patchNovelImport.mutate({ warn_threshold_chars: next })
  }

  const configSaving = save.isPending || patchNovelImport.isPending

  return (
    <PipelineSidePanel
      title="流水线配置"
      hint="本章写作参数（按当前小说）"
      skillContent={
        <>
          <PipelineConfigSection title="文风/过渡审查" hint="骨架扩写阶段跑哪些判官（可拖拽到画布对应节点启用、预览规则卡片）">
            <ReviewHookGroupSection novelId={novelId} group="buildtime" llmParamNodeId="review" onSelectNode={onSelectNode} />
          </PipelineConfigSection>

          <PipelineConfigSection title="设定质量审查" hint="设定持久化前跑哪些判官（可拖拽到画布对应节点启用、预览规则卡片）">
            <ReviewHookGroupSection novelId={novelId} group="setup" llmParamNodeId="setup_quality_review" onSelectNode={onSelectNode} />
          </PipelineConfigSection>
        </>
      }
    >
          <PipelineConfigSection title="对话agent 人物设定" hint="显示当前生效人设（默认或内容包覆写）；直接编辑并保存即成为本小说的覆写；「恢复默认」清除覆写">
            <div className="space-y-1.5">
              <Textarea
                aria-label="对话agent 人物设定"
                className="w-full min-h-[8rem] max-h-48 overflow-y-auto field-sizing-fixed text-xs"
                value={identity}
                onChange={e => setIdentityDraft(e.target.value)}
                onBlur={e => commitIdentity(e.target.value)}
              />
              <Button
                type="button"
                variant="link"
                onClick={() => commitIdentity('')}
                disabled={!hasIdentityOverride}
                className="h-auto p-0 text-[10px] text-[var(--c-text-muted)] hover:text-[var(--c-text-secondary)] disabled:opacity-30"
              >
                恢复默认
              </Button>
            </div>
          </PipelineConfigSection>

          <PipelineConfigSection title="章节字数目标" hint="骨架扩写时按权重换算建议拍数">
            <div className="space-y-2">
              <div className="flex items-baseline justify-between gap-2">
                <label className="flex items-baseline gap-1 text-sm text-[var(--c-accent)]">
                  <span className="font-medium shrink-0">约</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    aria-label="章节字数目标"
                    disabled={save.isPending}
                    value={wordsDraft ?? targetWords.toLocaleString('zh-CN')}
                    onFocus={() => setWordsDraft(String(targetWords))}
                    onChange={e => setWordsDraft(e.target.value.replace(/\D/g, ''))}
                    onBlur={() => commitWordsInput()}
                    onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }}
                    className={pipelinePanelWideCountInputClass}
                  />
                  <span className="font-medium shrink-0">字</span>
                </label>
                <span className={`${pipelinePanelHintClass} tabular-nums shrink-0`}>
                  {MIN_TARGET_WORDS.toLocaleString('zh-CN')} – {MAX_TARGET_WORDS.toLocaleString('zh-CN')}
                </span>
              </div>
              <input
                type="range"
                min={MIN_TARGET_WORDS}
                max={MAX_TARGET_WORDS}
                step={100}
                value={targetWords}
                onChange={e => setTargetWordsLocal(Number(e.target.value))}
                onPointerUp={e => persistTargetWords(Number(e.currentTarget.value))}
                onKeyUp={e => persistTargetWords(Number(e.currentTarget.value))}
                aria-label="章节字数滑块"
                className={rangeClass}
              />
            </div>
          </PipelineConfigSection>

          <PipelineConfigSection title="一键建设定" hint="AUTO 模式下 auto_build_setup 一次性建多少角色/章节">
            <div className="space-y-2">
              <label className="flex items-center justify-between gap-2 text-sm">
                <span className="text-[color:var(--c-text)]">角色数量</span>
                <input
                  type="text"
                  inputMode="numeric"
                  aria-label="角色数量"
                  disabled={save.isPending}
                  value={characterCountDraft ?? String(characterCount)}
                  onFocus={() => setCharacterCountDraft(String(characterCount))}
                  onChange={e => setCharacterCountDraft(e.target.value.replace(/\D/g, ''))}
                  onBlur={() => commitCharacterCountInput()}
                  onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }}
                  className={pipelinePanelCountInputClass}
                />
              </label>
              <label className="flex items-center justify-between gap-2 text-sm">
                <span className="text-[color:var(--c-text)]">章节数量</span>
                <input
                  type="text"
                  inputMode="numeric"
                  aria-label="章节数量"
                  disabled={save.isPending}
                  value={chapterCountDraft ?? String(chapterCount)}
                  onFocus={() => setChapterCountDraft(String(chapterCount))}
                  onChange={e => setChapterCountDraft(e.target.value.replace(/\D/g, ''))}
                  onBlur={() => commitChapterCountInput()}
                  onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }}
                  className={pipelinePanelCountInputClass}
                />
              </label>
            </div>
          </PipelineConfigSection>

          <PipelineConfigSection
            title="文本识别 · 小说导入"
            hint="导入小说建设定时的分片/压缩/字数提醒；并发度仅用于文风自动提取（全局配置，保存后立即生效）"
          >
            <div className="space-y-2">
              <label className="flex items-center justify-between gap-2 text-sm">
                <span className="text-[color:var(--c-text)]">分片字数</span>
                <input
                  type="text"
                  inputMode="numeric"
                  aria-label="分片字数"
                  disabled={configSaving}
                  value={chunkSizeDraft ?? String(novelImport.chunk_size)}
                  onFocus={() => setChunkSizeDraft(String(novelImport.chunk_size))}
                  onChange={e => setChunkSizeDraft(e.target.value.replace(/\D/g, ''))}
                  onBlur={e => commitChunkSize(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }}
                  className={pipelinePanelWideCountInputClass}
                />
              </label>
              <label className="flex items-center justify-between gap-2 text-sm">
                <span className="text-[color:var(--c-text)]">压缩间隔</span>
                <input
                  type="text"
                  inputMode="numeric"
                  aria-label="压缩间隔"
                  disabled={configSaving}
                  value={compactionDraft ?? String(novelImport.compaction_interval)}
                  onFocus={() => setCompactionDraft(String(novelImport.compaction_interval))}
                  onChange={e => setCompactionDraft(e.target.value.replace(/\D/g, ''))}
                  onBlur={e => commitCompactionInterval(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }}
                  className={pipelinePanelCountInputClass}
                />
              </label>
              <label className="flex items-center justify-between gap-2 text-sm">
                <span className="text-[color:var(--c-text)]">并发度</span>
                <input
                  type="text"
                  inputMode="numeric"
                  aria-label="并发度"
                  placeholder="不限"
                  disabled={configSaving}
                  value={concurrencyDraft ?? (novelImport.concurrency == null ? '' : String(novelImport.concurrency))}
                  onFocus={() => setConcurrencyDraft(
                    novelImport.concurrency == null ? '' : String(novelImport.concurrency),
                  )}
                  onChange={e => setConcurrencyDraft(e.target.value.replace(/\D/g, ''))}
                  onBlur={e => commitConcurrency(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }}
                  className={pipelinePanelCountInputClass}
                />
              </label>
              <label className="flex items-center justify-between gap-2 text-sm">
                <span className="text-[color:var(--c-text)]">字数提醒阈值</span>
                <input
                  type="text"
                  inputMode="numeric"
                  aria-label="字数提醒阈值"
                  disabled={configSaving}
                  value={warnThresholdDraft ?? String(novelImport.warn_threshold_chars)}
                  onFocus={() => setWarnThresholdDraft(String(novelImport.warn_threshold_chars))}
                  onChange={e => setWarnThresholdDraft(e.target.value.replace(/\D/g, ''))}
                  onBlur={e => commitWarnThreshold(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }}
                  className={pipelinePanelWideCountInputClass}
                />
              </label>
            </div>
          </PipelineConfigSection>
    </PipelineSidePanel>
  )
}
