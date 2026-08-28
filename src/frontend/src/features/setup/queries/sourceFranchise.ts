import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getSourceFranchise, setSourceFranchise } from '@/shared/utils/novels'
import { setupKey, sourceFranchiseKey } from '@/shared/queries/keys'

export function useSourceFranchise(novelId: string) {
  return useQuery<string>({
    queryKey: sourceFranchiseKey(novelId),
    queryFn: () => getSourceFranchise(novelId),
    enabled: !!novelId,
  })
}

export function useSetSourceFranchise(novelId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (franchise: string) => setSourceFranchise(novelId, franchise),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: sourceFranchiseKey(novelId) })
      // The backend re-enqueues whole-cast visual-tag extraction; the cast list will
      // pick up refreshed portrait_visual_tags on its next refetch.
      void queryClient.invalidateQueries({ queryKey: setupKey('cast', novelId) })
    },
  })
}
