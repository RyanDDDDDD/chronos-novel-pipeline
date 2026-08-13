import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchChronosConfig,
  saveChronosConfig,
  type NovelImportConfig,
} from '@/shared/utils/chronosConfig'
import { chronosConfigKey } from '@/shared/queries/keys'

export function useChronosConfig() {
  return useQuery({
    queryKey: chronosConfigKey,
    queryFn: fetchChronosConfig,
  })
}

export function usePatchNovelImportConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (patch: Partial<NovelImportConfig>) => {
      const current = await fetchChronosConfig()
      return saveChronosConfig({
        ...current,
        novel_import: { ...(current.novel_import ?? {}), ...patch },
      })
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: chronosConfigKey }),
  })
}
