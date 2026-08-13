import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import type { RootState } from '@/shared/store/store'
import { wsEventReceived } from '@/shared/store/wsActions'

export type NovelImportState = {
  status: 'idle' | 'running' | 'done' | 'error'
  /** Which granularity the current index/total pair counts in -- 'text' is text-chunk
   * count (read_attachment's per-chunk distillation progress), 'image' is image count
   * (aggregate across however many read_attachment_image calls this turn makes). The two
   * event families are mutually exclusive within one turn's attachment_ids in practice, so
   * one shared status region can just show whichever kind's events arrived most recently. */
  kind: 'text' | 'image'
  index: number
  total: number
  error?: string
}

const IDLE: NovelImportState = { status: 'idle', kind: 'text', index: 0, total: 0 }

interface NovelImportSliceState {
  byNovelId: Record<string, NovelImportState>
}

const initialState: NovelImportSliceState = { byNovelId: {} }

function ensure(state: NovelImportSliceState, novelId: string): NovelImportState {
  return state.byNovelId[novelId] ??= { ...IDLE }
}

function reduceNovelImportEvent(
  prev: NovelImportState,
  data: { type: string; total?: number; index?: number; ok?: boolean; error?: string; cancelled?: boolean },
): NovelImportState {
  switch (data.type) {
    case 'novel_import_start':
      return { status: 'running', kind: 'text', index: 0, total: data.total ?? 0 }
    case 'novel_import_progress':
      return {
        ...prev,
        kind: 'text',
        status: data.ok === false ? prev.status : 'running',
        index: data.index ?? prev.index,
        total: data.total ?? prev.total,
        error: data.ok === false ? data.error : prev.error,
      }
    case 'novel_import_done':
      return { ...prev, status: 'done', index: prev.total }
    case 'novel_import_image_start':
      return { status: 'running', kind: 'image', index: 0, total: data.total ?? 0 }
    case 'novel_import_image_progress':
      return {
        ...prev,
        kind: 'image',
        status: data.ok === false ? prev.status : 'running',
        index: data.index ?? prev.index,
        total: data.total ?? prev.total,
        error: data.ok === false ? data.error : prev.error,
      }
    case 'novel_import_image_done':
      if (data.cancelled) return { ...IDLE }
      return { ...prev, status: 'done', index: prev.total }
    default:
      return prev
  }
}

export const fetchNovelImportProgress = createAsyncThunk(
  'novelImport/fetchProgress',
  async (novelId: string): Promise<{ novelId: string; progress: NovelImportState | null }> => {
    try {
      const res = await fetch(`/api/setup-chat/status?novel_id=${encodeURIComponent(novelId)}`)
      const body = await res.json().catch(() => ({}))
      const raw = body.novel_import
      if (!raw || raw.status !== 'running') {
        return { novelId, progress: null }
      }
      return {
        novelId,
        progress: {
          status: 'running',
          kind: raw.kind === 'image' ? 'image' : 'text',
          index: Number(raw.index ?? 0),
          total: Number(raw.total ?? 0),
          ...(raw.error ? { error: String(raw.error) } : {}),
        },
      }
    } catch {
      return { novelId, progress: null }
    }
  },
)

const novelImportSlice = createSlice({
  name: 'novelImport',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(wsEventReceived, (state, action) => {
        const { type, novel_id: novelId } = action.payload
        if (!novelId) return
        const next = reduceNovelImportEvent(ensure(state, novelId), { ...action.payload, type })
        if (next === state.byNovelId[novelId]) return
        state.byNovelId[novelId] = next
      })
      .addCase(fetchNovelImportProgress.fulfilled, (state, action) => {
        const { novelId, progress } = action.payload
        if (progress?.status === 'running') {
          state.byNovelId[novelId] = progress
          return
        }
        if (state.byNovelId[novelId]?.status === 'running') {
          delete state.byNovelId[novelId]
        }
      })
  },
})

export const selectNovelImportProgress = (novelId: string) => (state: RootState): NovelImportState =>
  state.novelImport.byNovelId[novelId] ?? IDLE

export default novelImportSlice.reducer
