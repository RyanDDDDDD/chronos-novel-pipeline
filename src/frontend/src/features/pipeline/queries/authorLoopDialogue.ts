import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchDialogueConfig, putDialogueConfig } from '@/features/pipeline/utils/authorLoopDialogueConfig'
import { authorLoopDialogueKey } from '@/shared/queries/keys'

export function useAuthorLoopDialogueConfig(novelId: string) {
  return useQuery({
    queryKey: authorLoopDialogueKey(novelId),
    queryFn: () => fetchDialogueConfig(novelId),
    enabled: !!novelId,
  })
}

export function useSetAuthorLoopDialogueConfig(novelId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Parameters<typeof putDialogueConfig>[1]) => putDialogueConfig(novelId, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: authorLoopDialogueKey(novelId) }),
  })
}
