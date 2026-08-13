/** Single accumulation or token usage of ledger cell (aligned with backend Cell).*/
export interface TokenUsage {
  tokens_in: number
  tokens_out: number
  tokens_cached: number
}

export const EMPTY_TOKEN_USAGE: TokenUsage = {
  tokens_in: 0,
  tokens_out: 0,
  tokens_cached: 0,
}

export function resolveTokenUsage(usage: TokenUsage | null | undefined): TokenUsage {
  if (!usage) return EMPTY_TOKEN_USAGE
  return usage
}

/** Thousandths; use zh-CN consistent with the page locale.*/
export function formatTokenCount(n: number): string {
  return n.toLocaleString('zh-CN')
}
