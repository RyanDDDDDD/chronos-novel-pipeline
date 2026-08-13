import { useQuery } from '@tanstack/react-query'
import { manuscriptChaptersKey, manuscriptKey } from '@/shared/queries/keys'

export interface ManuscriptChapter {
  chapter: number
  path: string
}

export interface ChapterManuscript {
  chapter: number
  path: string
  content: string
}

export async function fetchManuscriptChapters(): Promise<ManuscriptChapter[]> {
  const data: { chapters?: ManuscriptChapter[] } = await fetch('/api/chapters/manuscripts')
    .then(r => r.json())
    .catch(() => ({ chapters: [] }))
  return (
    data.chapters?.filter(
      (c): c is ManuscriptChapter => typeof c?.chapter === 'number' && c.chapter > 0,
    ) ?? []
  )
}

export async function fetchChapterManuscript(chapter: number): Promise<ChapterManuscript | null> {
  const res = await fetch(`/api/chapters/${chapter}/manuscript`)
  const body = await res.json().catch(() => ({}))
  if (res.status === 404) return null
  if (!res.ok || body.ok === false) {
    throw new Error(body.error ?? `加载失败 (HTTP ${res.status})`)
  }
  return {
    chapter: body.chapter ?? chapter,
    path: String(body.path ?? ''),
    content: String(body.content ?? ''),
  }
}

export function useManuscriptChapters(novelId: string) {
  return useQuery({
    queryKey: manuscriptChaptersKey(novelId),
    queryFn: fetchManuscriptChapters,
    enabled: !!novelId,
  })
}

export function useChapterManuscript(novelId: string, chapter: number) {
  return useQuery({
    queryKey: manuscriptKey(novelId, chapter),
    queryFn: () => fetchChapterManuscript(chapter),
    enabled: !!novelId && chapter >= 1,
  })
}
