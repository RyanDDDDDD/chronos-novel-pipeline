import type { ArchiveOverview, CharacterArchive, ChapterArchives, SandboxMemoryEntry } from '@/shared/types'

export async function fetchArchiveOverview(): Promise<ArchiveOverview> {
  const res = await fetch('/api/archives')
  const body = await res.json().catch(() => ({}))
  return { built: body.built ?? [], plot_chapters: body.plot_chapters ?? [] }
}

export async function fetchChapterArchives(chapter: number): Promise<ChapterArchives> {
  const res = await fetch(`/api/archives/${chapter}`)
  const body = await res.json().catch(() => ({}))
  return { chapter, characters: body.characters ?? [] }
}

export async function fetchSandboxCastArchives(
  chapter: number,
  names: string[],
  novelId: string,
): Promise<{ characters: CharacterArchive[] }> {
  const params = new URLSearchParams({
    chapter: String(chapter),
    names: names.join(','),
    novel_id: novelId,
  })
  const res = await fetch(`/api/story-sandbox/cast-archives?${params}`)
  const body = await res.json().catch(() => ({}))
  return { characters: body.characters ?? [] }
}

export async function fetchSandboxRelatedCastArchives(
  chapter: number,
  present: string[],
  novelId: string,
): Promise<{ characters: CharacterArchive[] }> {
  const params = new URLSearchParams({
    chapter: String(chapter),
    present: present.join(','),
    novel_id: novelId,
  })
  const res = await fetch(`/api/story-sandbox/related-cast-archives?${params}`)
  const body = await res.json().catch(() => ({}))
  return { characters: body.characters ?? [] }
}

function parseMemoryEntry(raw: Record<string, unknown>): SandboxMemoryEntry {
  return {
    id: String(raw.id ?? ''), chapter: Number(raw.chapter ?? 0), turnIndex: Number(raw.turn_index ?? 0),
    time: String(raw.time ?? ''), location: String(raw.location ?? ''),
    characters: Array.isArray(raw.characters) ? raw.characters.map(String) : [],
    summary: String(raw.summary ?? ''),
    entities: Array.isArray(raw.entities) ? raw.entities.map(String) : [],
    branchId: raw.branch_id == null ? null : String(raw.branch_id),
  }
}

export async function fetchSandboxMemoryArchive(
  chapter: number, branchId: string | null,
): Promise<SandboxMemoryEntry[]> {
  const params = new URLSearchParams({ chapter: String(chapter) })
  if (branchId) params.set('branch_id', branchId)
  const res = await fetch(`/api/story-sandbox/memory-archive?${params}`)
  const body = await res.json().catch(() => ({}))
  const raw = Array.isArray((body as { entries?: unknown[] }).entries)
    ? (body as { entries: Record<string, unknown>[] }).entries
    : []
  return raw.map(parseMemoryEntry)
}
