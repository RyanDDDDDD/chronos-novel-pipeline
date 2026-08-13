import { useQuery } from '@tanstack/react-query'
import {
  fetchWorld, fetchCast, fetchPlot, fetchSetupSkills, fetchRelationshipGraph, fetchCustomFields,
} from '@/shared/utils/setup'
import { useActiveNovelId } from '@/shared/queries/novels'
import { setupKey, setupSkillsKey, relationshipGraphKey } from '@/shared/queries/keys'

export function useWorld() {
  const novelId = useActiveNovelId()
  return useQuery({ queryKey: setupKey('world', novelId), queryFn: fetchWorld, enabled: !!novelId })
}

export function useRelationshipGraph() {
  const novelId = useActiveNovelId()
  return useQuery({
    queryKey: relationshipGraphKey(novelId), queryFn: fetchRelationshipGraph, enabled: !!novelId,
  })
}

export function useCast() {
  const novelId = useActiveNovelId()
  return useQuery({ queryKey: setupKey('cast', novelId), queryFn: fetchCast, enabled: !!novelId })
}

export function usePlot() {
  const novelId = useActiveNovelId()
  return useQuery({ queryKey: setupKey('plot', novelId), queryFn: fetchPlot, enabled: !!novelId })
}

export function useSetupSkills() {
  // skill 列表基本静态（改文件才变），5 分钟内不重拉
  return useQuery({ queryKey: setupSkillsKey, queryFn: fetchSetupSkills, staleTime: 5 * 60_000 })
}

export function useCustomFields() {
  return useQuery({
    queryKey: ['custom-fields'],
    queryFn: fetchCustomFields,
    staleTime: 5 * 60_000,
  })
}
