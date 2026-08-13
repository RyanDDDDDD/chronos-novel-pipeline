import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { chaptersKey } from '@/shared/queries/keys'

export interface ChapterOption {
  chapter: number
  title?: string | null
}

export async function fetchChapters(): Promise<ChapterOption[]> {
  const data: { chapters?: ChapterOption[] } = await fetch('/api/chapters')
    .then(r => r.json())
    .catch(() => ({ chapters: [] }))
  return (
    data.chapters?.filter(
      (c): c is ChapterOption => typeof c?.chapter === 'number' && c.chapter > 0,
    ) ?? []
  )
}

export function useChapters(novelId: string) {
  return useQuery({
    queryKey: chaptersKey(novelId),
    queryFn: fetchChapters,
    enabled: !!novelId,
  })
}

/** availableChapters (from useChapters) unioned with the currently-selected chapter (so a
 * chapter picked before its own outline exists doesn't vanish from the dropdown), deduped and
 * sorted. Shared by AuthorLoopPage/ChapterManuscriptPage/StorySandboxPage -- previously computed
 * once in App.tsx and threaded down as a `chapters` prop to all three. */
export function useChapterNumbers(novelId: string, chapter: number): number[] {
  const { data: availableChapters = [{ chapter: 1, title: null }] } = useChapters(novelId)
  return useMemo(() => {
    const nums = availableChapters.map(c => c.chapter)
    if (!nums.includes(chapter)) nums.push(chapter)
    return [...new Set(nums)].sort((a, b) => a - b)
  }, [availableChapters, chapter])
}
