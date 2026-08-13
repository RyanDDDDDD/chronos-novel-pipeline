import { useQuery } from '@tanstack/react-query'
import { fetchArtStylePresets } from '@/features/services/utils/llmCatalog'
import { artStylePresetsKey } from '@/shared/queries/keys'

export function useArtStylePresets() {
  return useQuery({ queryKey: artStylePresetsKey, queryFn: fetchArtStylePresets })
}
