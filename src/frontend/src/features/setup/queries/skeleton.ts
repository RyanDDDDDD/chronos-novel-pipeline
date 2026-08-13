import { useQuery } from '@tanstack/react-query'
import { fetchChapterSkeleton } from '@/features/setup/utils/skeleton'
import { useActiveNovelId } from '@/shared/queries/novels'
import { skeletonKey } from '@/shared/queries/keys'

export function useChapterSkeleton(chapter: number | null) {
  const novelId = useActiveNovelId()
  return useQuery({
    queryKey: skeletonKey(novelId, chapter ?? -1),
    queryFn: () => fetchChapterSkeleton(chapter as number),
    enabled: !!novelId && chapter != null,
  })
}
