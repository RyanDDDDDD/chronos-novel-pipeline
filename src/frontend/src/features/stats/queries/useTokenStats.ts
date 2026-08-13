import { useQuery } from "@tanstack/react-query";
import { tokenStatsKey } from "@/shared/queries/keys";
import { fetchTokenStats } from "@/features/stats/utils/tokenStatsApi";

export function useTokenStats() {
  return useQuery({ queryKey: tokenStatsKey, queryFn: fetchTokenStats });
}
