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
  reducers: {},
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

export default cloudAuthSlice.reducer
