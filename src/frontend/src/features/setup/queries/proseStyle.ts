import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  listProseStyles, getProseStyle, setProseStyle, getProseStylePresetContent,
  type ProseStyleConfig, type ProseStylePreset, type ProseStylePresetContent,
} from '@/shared/utils/novels'
import { proseStylesKey, proseStyleKey, proseStylePresetContentKey } from '@/shared/queries/keys'

export function useProseStyles() {
  return useQuery<ProseStylePreset[]>({ queryKey: proseStylesKey, queryFn: listProseStyles })
}

export function useProseStylePresetContent(presetId: string, enabled: boolean) {
  return useQuery<ProseStylePresetContent | null>({
    queryKey: proseStylePresetContentKey(presetId),
    queryFn: () => getProseStylePresetContent(presetId),
    enabled: enabled && !!presetId,
  })
}

export function useProseStyle(novelId: string) {
  return useQuery<ProseStyleConfig>({
    queryKey: proseStyleKey(novelId),
    queryFn: () => getProseStyle(novelId),
    enabled: !!novelId,
  })
}

export function useSetProseStyle(novelId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (config: ProseStyleConfig) => setProseStyle(novelId, config),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: proseStyleKey(novelId) }),
  })
}
