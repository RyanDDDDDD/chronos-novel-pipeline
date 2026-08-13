import { useQuery } from '@tanstack/react-query'
import { listStateDeriveFields } from '@/shared/utils/novels'
import { stateDeriveFieldsKey } from '@/shared/queries/keys'
import { BASELINE_STATE_DERIVE_FIELDS } from '@/shared/utils/characterStateFields'
import type { StateDeriveFieldSpec } from '@/shared/types'

export function useStateDeriveFields(): {
  fields: StateDeriveFieldSpec[]
  isLoading: boolean
} {
  const query = useQuery<StateDeriveFieldSpec[]>({
    queryKey: stateDeriveFieldsKey,
    queryFn: listStateDeriveFields,
    staleTime: 60_000,
  })
  return {
    fields: query.data?.length ? query.data : BASELINE_STATE_DERIVE_FIELDS,
    isLoading: query.isLoading,
  }
}
