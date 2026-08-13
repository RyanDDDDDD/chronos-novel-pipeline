import { createAsyncThunk } from '@reduxjs/toolkit'
import type { AppDispatch } from '@/shared/store/store'
import { fetchNovelImportProgress } from '@/features/chat/store/novelImportSlice'
import { resetAuthorLoop, fetchAuthorLoopStatus } from '@/features/author/store/authorLoopSlice'
import { resetSetupChat, fetchSetupChatStatus } from '@/features/chat/store/setupChatSlice'
import { resetSandbox } from '@/features/sandbox/store/sandboxSlice'
import { clearTokenUsage } from '@/shared/store/tokenUsageSlice'

export const resetForNovelSwitch = createAsyncThunk(
  'app/resetForNovelSwitch',
  async (novelId: string, { dispatch }) => {
    const d = dispatch as AppDispatch
    d(resetAuthorLoop())
    d(resetSetupChat(novelId))
    d(resetSandbox())
    d(clearTokenUsage())
    await d(fetchAuthorLoopStatus(novelId))
    // resetSetupChat() above unconditionally zeroes busy; if setup_chat is still generating for
    // this novel (multi-novel concurrency lets that happen while the user was elsewhere), an
    // explicit novel_id-scoped resync is the only thing that catches it back up -- the composer's
    // disabled state would otherwise silently read "idle" until the next WS event.
    await d(fetchSetupChatStatus(novelId))
    await d(fetchNovelImportProgress(novelId))
  },
)
