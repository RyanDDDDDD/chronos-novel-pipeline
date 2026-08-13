import { createSlice } from '@reduxjs/toolkit'
import type { RootState } from '@/shared/store/store'

const connectionSlice = createSlice({
  name: 'connection',
  initialState: { connected: false },
  reducers: {
    wsConnected: (state) => { state.connected = true },
    wsDisconnected: (state) => { state.connected = false },
  },
})

export const { wsConnected, wsDisconnected } = connectionSlice.actions
export const selectConnected = (state: RootState): boolean => state.connection.connected
export default connectionSlice.reducer
