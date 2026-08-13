import { createSlice } from '@reduxjs/toolkit'
import type { RootState } from '@/shared/store/store'
import { wsEventReceived } from '@/shared/store/wsActions'

export interface TokenUsageCell {
  tokens_in: number
  tokens_out: number
  tokens_cached: number
}

export function tokenUsageKey(subsystem: string, key: string): string {
  return `${subsystem}:${key}`
}

const tokenUsageSlice = createSlice({
  name: 'tokenUsage',
  initialState: {} as Record<string, TokenUsageCell>,
  reducers: {
    clearTokenUsage: () => ({}),
  },
  extraReducers: (builder) => {
    builder.addCase(wsEventReceived, (state, action) => {
      const data = action.payload
      if (data.type !== 'token_usage') return
      const sub = data.subsystem ?? ''
      const key = data.key ?? ''
      if (!sub || !key) return
      state[tokenUsageKey(sub, key)] = {
        tokens_in: data.tokens_in ?? data.input ?? 0,
        tokens_out: data.tokens_out ?? data.output ?? 0,
        tokens_cached: data.tokens_cached ?? data.cached ?? 0,
      }
    })
  },
})

export const { clearTokenUsage } = tokenUsageSlice.actions
export const selectTokenUsage = (subsystem: string, key: string) =>
  (state: RootState): TokenUsageCell | null =>
    state.tokenUsage[tokenUsageKey(subsystem, key)] ?? null

export default tokenUsageSlice.reducer
