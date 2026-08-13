import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getSandboxDialogueTurnCount, setSandboxDialogueTurnCount } from '@/shared/utils/novels'
import { sandboxDialogueTurnCountKey } from '@/shared/queries/keys'

export function useSandboxDialogueTurnCount(novelId: string) {
  return useQuery<number | null>({
    queryKey: sandboxDialogueTurnCountKey(novelId),
    queryFn: () => getSandboxDialogueTurnCount(novelId),
    enabled: !!novelId,
  })
}

export function useSetSandboxDialogueTurnCount(novelId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (turnCount: number | null) => setSandboxDialogueTurnCount(novelId, turnCount),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sandboxDialogueTurnCountKey(novelId) }),
  })
}
