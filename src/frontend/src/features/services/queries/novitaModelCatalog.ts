import { useQuery } from '@tanstack/react-query'
import { novitaModelCatalogKey } from '@/shared/queries/keys'
import { fetchNovitaModelCatalog } from '@/features/services/utils/llmCatalog'

export function useNovitaModelCatalog() {
  return useQuery({ queryKey: novitaModelCatalogKey, queryFn: fetchNovitaModelCatalog })
}
