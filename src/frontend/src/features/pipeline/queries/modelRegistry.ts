import { useQuery } from '@tanstack/react-query'
import { fetchModelRegistry, fetchImageGenModelRegistry } from '@/features/services/utils/llmCatalog'
import { imageGenModelRegistryKey, modelRegistryKey } from '@/shared/queries/keys'

export function useModelRegistry() {
  return useQuery({ queryKey: modelRegistryKey, queryFn: fetchModelRegistry })
}

export function useImageGenModelRegistry() {
  return useQuery({ queryKey: imageGenModelRegistryKey, queryFn: fetchImageGenModelRegistry })
}
