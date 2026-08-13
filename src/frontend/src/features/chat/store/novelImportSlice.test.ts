import { describe, it, expect } from 'vitest'
import novelImportReducer, {
  fetchNovelImportProgress,
  selectNovelImportProgress,
} from '@/features/chat/store/novelImportSlice'
import { wsEventReceived } from '@/shared/store/wsActions'

const idle = { status: 'idle' as const, kind: 'text' as const, index: 0, total: 0 }
const initial = { byNovelId: {} }

describe('novelImportSlice', () => {
  it('starts idle', () => {
    expect(novelImportReducer(undefined, { type: '@@INIT' })).toEqual(initial)
  })

  it('novel_import_start resets counters per novel, enters running, kind=text', () => {
    const prev = {
      byNovelId: {
        'novel-a': { status: 'done' as const, kind: 'image' as const, index: 5, total: 5 },
      },
    }
    const state = novelImportReducer(
      prev,
      wsEventReceived({ type: 'novel_import_start', total: 8, novel_id: 'novel-b' }),
    )
    expect(state.byNovelId['novel-a']).toEqual(prev.byNovelId['novel-a'])
    expect(state.byNovelId['novel-b']).toEqual({ status: 'running', kind: 'text', index: 0, total: 8 })
  })

  it('novel_import_progress updates index/total and stays running on ok', () => {
    const prev = {
      byNovelId: {
        'novel-a': { status: 'running' as const, kind: 'text' as const, index: 0, total: 8 },
      },
    }
    const state = novelImportReducer(
      prev,
      wsEventReceived({ type: 'novel_import_progress', index: 3, total: 8, ok: true, novel_id: 'novel-a' }),
    )
    expect(state.byNovelId['novel-a']).toEqual({ status: 'running', kind: 'text', index: 3, total: 8 })
  })

  it('novel_import_progress with ok=false records error without flipping status', () => {
    const prev = {
      byNovelId: {
        'novel-a': { status: 'running' as const, kind: 'text' as const, index: 2, total: 8 },
      },
    }
    const state = novelImportReducer(
      prev,
      wsEventReceived({ type: 'novel_import_progress', ok: false, error: '分片提炼失败', novel_id: 'novel-a' }),
    )
    expect(state.byNovelId['novel-a']?.status).toBe('running')
    expect(state.byNovelId['novel-a']?.error).toBe('分片提炼失败')
  })

  it('novel_import_done marks done and fills index to total', () => {
    const prev = {
      byNovelId: {
        'novel-a': { status: 'running' as const, kind: 'text' as const, index: 7, total: 8 },
      },
    }
    const state = novelImportReducer(
      prev,
      wsEventReceived({ type: 'novel_import_done', novel_id: 'novel-a' }),
    )
    expect(state.byNovelId['novel-a']).toEqual({ status: 'done', kind: 'text', index: 8, total: 8 })
  })

  it('novel_import_image_start resets counters, enters running, kind=image', () => {
    const state = novelImportReducer(
      initial,
      wsEventReceived({ type: 'novel_import_image_start', total: 3, novel_id: 'novel-a' }),
    )
    expect(state.byNovelId['novel-a']).toEqual({ status: 'running', kind: 'image', index: 0, total: 3 })
  })

  it('novel_import_image_done with cancelled resets to idle', () => {
    const running = {
      byNovelId: {
        'novel-a': { status: 'running' as const, kind: 'image' as const, index: 0, total: 3 },
      },
    }
    const state = novelImportReducer(
      running,
      wsEventReceived({ type: 'novel_import_image_done', novel_id: 'novel-a', cancelled: true }),
    )
    expect(state.byNovelId['novel-a']).toEqual({ status: 'idle', kind: 'text', index: 0, total: 0 })
  })

  it('ignores events without novel_id', () => {
    const prev = {
      byNovelId: {
        'novel-a': { status: 'running' as const, kind: 'text' as const, index: 2, total: 8 },
      },
    }
    const state = novelImportReducer(prev, wsEventReceived({ type: 'novel_import_progress', index: 3, total: 8, ok: true }))
    expect(state).toEqual(prev)
  })

  it('fetchNovelImportProgress restores running progress for the target novel', () => {
    const state = novelImportReducer(
      initial,
      fetchNovelImportProgress.fulfilled(
        {
          novelId: 'novel-a',
          progress: { status: 'running', kind: 'image', index: 2, total: 5 },
        },
        '',
        'novel-a',
      ),
    )
    expect(state.byNovelId['novel-a']).toEqual({ status: 'running', kind: 'image', index: 2, total: 5 })
  })

  it('fetchNovelImportProgress clears stale running state when backend reports idle', () => {
    const prev = {
      byNovelId: {
        'novel-a': { status: 'running' as const, kind: 'image' as const, index: 2, total: 5 },
      },
    }
    const state = novelImportReducer(
      prev,
      fetchNovelImportProgress.fulfilled({ novelId: 'novel-a', progress: null }, '', 'novel-a'),
    )
    expect(state.byNovelId['novel-a']).toBeUndefined()
  })

  it('selectNovelImportProgress reads per-novel state with idle fallback', () => {
    expect(selectNovelImportProgress('novel-a')({
      novelImport: {
        byNovelId: { 'novel-a': { status: 'running', kind: 'text', index: 1, total: 4 } },
      },
    } as never)).toEqual({ status: 'running', kind: 'text', index: 1, total: 4 })
    expect(selectNovelImportProgress('novel-b')({ novelImport: initial } as never)).toEqual(idle)
  })
})
