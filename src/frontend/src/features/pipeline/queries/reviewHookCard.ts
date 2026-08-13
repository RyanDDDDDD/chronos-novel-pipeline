import { useQuery } from '@tanstack/react-query'
import { fetchReviewHookCard } from '@/features/pipeline/utils/reviewHookCard'
import { reviewHookCardKey } from '@/shared/queries/keys'

export function useReviewHookCard(name: string, enabled: boolean) {
  return useQuery({
    queryKey: reviewHookCardKey(name),
    queryFn: () => fetchReviewHookCard(name),
    enabled: enabled && !!name,
  })
}
