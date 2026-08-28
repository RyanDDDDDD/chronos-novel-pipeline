import { createSlice } from '@reduxjs/toolkit'
import { wsEventReceived } from '@/shared/store/wsActions'

interface CloudAuthState {
  isLoggedIn: boolean
  lastErrorCode: string | null
}

const initialState: CloudAuthState = { isLoggedIn: false, lastErrorCode: null }

const cloudAuthSlice = createSlice({
  name: 'cloudAuth',
  initialState,
  reducers: {
    // Hydrates isLoggedIn from GET /api/auth/status (backed by the OS keyring, which
    // survives process restarts) -- the WS events below only cover state changes that
    // happen while this tab is open, so a fresh page load needs this to reflect an
    // already-logged-in session instead of defaulting to false.
    loginStatusHydrated(state, action: { payload: boolean }) {
      state.isLoggedIn = action.payload
    },
  },
  extraReducers: (builder) => {
    builder.addCase(wsEventReceived, (state, action) => {
      const { type, error_code } = action.payload
      if (type === 'cloud_auth_login_succeeded') {
        state.isLoggedIn = true
        state.lastErrorCode = null
      } else if (type === 'cloud_auth_login_failed') {
        state.lastErrorCode = error_code ?? null
      } else if (type === 'cloud_auth_logged_out') {
        state.isLoggedIn = false
      }
    })
  },
})

export const { loginStatusHydrated } = cloudAuthSlice.actions
export default cloudAuthSlice.reducer
