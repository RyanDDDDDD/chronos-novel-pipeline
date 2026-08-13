import { useQuery } from '@tanstack/react-query'
import { fetchArchiveOverview, fetchChapterArchives } from '@/shared/utils/archives'
import { useActiveNovelId } from '@/shared/queries/novels'
import { archivesKey } from '@/shared/queries/keys'

export function useArchiveOverview() {
  const novelId = useActiveNovelId()
  return useQuery({ queryKey: archivesKey(novelId), queryFn: fetchArchiveOverview, enabled: !!novelId })
}

export function useChapterArchives(chapter: number | null) {
  const novelId = useActiveNovelId()
  return useQuery({
    queryKey: archivesKey(novelId, chapter ?? -1),
    queryFn: () => fetchChapterArchives(chapter as number),
    enabled: !!novelId && chapter != null,
  })
}
