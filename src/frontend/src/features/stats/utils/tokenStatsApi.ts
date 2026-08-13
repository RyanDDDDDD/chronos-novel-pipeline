import type { TokenStatsResponse } from "@/features/stats/utils/tokenStatsModel";

export async function fetchTokenStats(): Promise<TokenStatsResponse> {
  const res = await fetch("/api/token-stats");
  if (!res.ok) throw new Error(`token-stats HTTP ${res.status}`);
  return res.json();
}
