import { countManuscriptChars } from '@/shared/utils/manuscriptText'

export interface SkeletonBeat {
  text: string
  sensation_notes?: string[]
  dialogue_draft?: string
}
export interface SkeletonStage {
  stage_num: number
  title: string
  description: string
  location: string
  beats: SkeletonBeat[]
  expanded: boolean
}
export interface ChapterSkeleton {
  chapter: number
  exists: boolean
  stages: SkeletonStage[]
}

export interface SkeletonStageCharCounts {
  stage_num: number
  outline: number
  beats: number
}

export interface SkeletonChapterCharCounts {
  stages: SkeletonStageCharCounts[]
  outlineTotal: number
  beatsTotal: number
}

export function countSkeletonOutlineChars(description: string): number {
  return countManuscriptChars(description)
}

export function countSkeletonBeatsChars(beats: SkeletonBeat[]): number {
  return beats.reduce((sum, b) => sum + countManuscriptChars(b.text), 0)
}

export function computeSkeletonCharCounts(stages: SkeletonStage[]): SkeletonChapterCharCounts {
  const stageRows = stages.map((s) => ({
    stage_num: s.stage_num,
    outline: countSkeletonOutlineChars(s.description),
    beats: countSkeletonBeatsChars(s.beats),
  }))
  return {
    stages: stageRows,
    outlineTotal: stageRows.reduce((sum, s) => sum + s.outline, 0),
    beatsTotal: stageRows.reduce((sum, s) => sum + s.beats, 0),
  }
}

/** 读某章逐 stage 的分拍底稿（粗大纲 description + 对话页扩写的 beats + 是否已扩写）。*/
export async function fetchChapterSkeleton(chapter: number): Promise<ChapterSkeleton> {
  const res = await fetch(`/api/setup/skeleton/${chapter}`)
  const body = await res.json().catch(() => ({}))
  return {
    chapter,
    exists: body.exists ?? false,
    stages: body.stages ?? [],
  }
}

export type SkeletonPatchOp =
  | { op: 'replace'; stage_num: number; fields: Record<string, unknown> }
  | { op: 'replace_beat'; stage_num: number; beat_idx: number; beat: { text: string; sensation_notes?: string[]; dialogue_draft?: string } }
  | { op: 'set_beat_dialogue'; stage_num: number; beat_idx: number; dialogue_draft: string }

export async function patchSkeletonStage(
  chapter: number,
  op: SkeletonPatchOp,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const res = await fetch(`/api/setup/plot/${chapter}/skeleton`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(op),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok || body.ok === false) {
    return { ok: false, error: body.error ?? `请求失败 (HTTP ${res.status})` }
  }
  return { ok: true }
}
