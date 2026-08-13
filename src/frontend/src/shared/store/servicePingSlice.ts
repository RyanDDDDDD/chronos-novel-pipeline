import { createSlice, type PayloadAction } from '@reduxjs/toolkit'
import type { RootState } from '@/shared/store/store'

export type PingTarget = 'llm' | 'search'
export type PingStatus = 'unknown' | 'checking' | 'ok' | 'error' | 'disabled'

export interface PingEntry {
  status: PingStatus
  error: string | null
}

interface ServicePingState {
  llm: PingEntry
  search: PingEntry
}

export type { ServicePingState }

const idleEntry: PingEntry = { status: 'unknown', error: null }
const initialState: ServicePingState = { llm: idleEntry, search: idleEntry }

const servicePingSlice = createSlice({
  name: 'servicePing',
  initialState,
  reducers: {
    pingStarted: (state, action: PayloadAction<PingTarget>) => {
      state[action.payload] = { status: 'checking', error: null }
    },
    pingSucceeded: (state, action: PayloadAction<PingTarget>) => {
      state[action.payload] = { status: 'ok', error: null }
    },
    pingFailed: (state, action: PayloadAction<{ target: PingTarget; error: string }>) => {
      state[action.payload.target] = { status: 'error', error: action.payload.error }
    },
    pingDisabled: (state, action: PayloadAction<PingTarget>) => {
      state[action.payload] = { status: 'disabled', error: null }
    },
    serviceStatusLoaded: (state, action: PayloadAction<ServicePingState>) => {
      state.llm = action.payload.llm
      state.search = action.payload.search
    },
  },
})

export const { pingStarted, pingSucceeded, pingFailed, pingDisabled, serviceStatusLoaded } = servicePingSlice.actions
export const selectServicePing = (state: RootState): ServicePingState => state.servicePing
export default servicePingSlice.reducer
