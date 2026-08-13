import { describe, it, expect } from 'vitest'
import viewUnreadReducer, { viewFocusChanged, selectViewUnreadForNovel } from '@/shared/store/viewUnreadSlice'
import { wsEventReceived } from '@/shared/store/wsActions'
import type { RootState } from '@/shared/store/store'

describe('viewUnreadSlice', () => {
  it('marks a novel unread when its event arrives while another novel is focused', () => {
    let state = viewUnreadReducer(undefined, viewFocusChanged({
      novelId: 'novel-B', view: 'author', isArchives: false,
    }))
    state = viewUnreadReducer(state, wsEventReceived({ type: 'author_loop_done', novel_id: 'novel-A' }))

    expect(state.byNovelId['novel-A'].author).toBe(true)
    expect(state.byNovelId['novel-B']).toBeUndefined()
  })

  it('does not leak the badge onto whatever novel is currently focused', () => {
    const state = viewUnreadReducer(undefined, viewFocusChanged({
      novelId: 'novel-B', view: 'chat', isArchives: false,
    }))
    const next = viewUnreadReducer(state, wsEventReceived({ type: 'author_loop_done', novel_id: 'novel-A' }))

    expect(next.byNovelId['novel-B']).toBeUndefined()
  })

  it('suppresses the badge for the focused novel while its own tab is open', () => {
    const state = viewUnreadReducer(undefined, viewFocusChanged({
      novelId: 'novel-A', view: 'author', isArchives: false,
    }))
    const next = viewUnreadReducer(state, wsEventReceived({ type: 'author_loop_token', novel_id: 'novel-A' }))

    expect(next.byNovelId['novel-A']).toBeUndefined()
  })

  it('marks the focused novel unread when the event targets a different tab', () => {
    const state = viewUnreadReducer(undefined, viewFocusChanged({
      novelId: 'novel-A', view: 'chat', isArchives: false,
    }))
    const next = viewUnreadReducer(state, wsEventReceived({ type: 'author_loop_done', novel_id: 'novel-A' }))

    expect(next.byNovelId['novel-A'].author).toBe(true)
  })

  it('clears a novel badge when focus moves onto its tab', () => {
    let state = viewUnreadReducer(undefined, viewFocusChanged({
      novelId: 'novel-B', view: 'chat', isArchives: false,
    }))
    state = viewUnreadReducer(state, wsEventReceived({ type: 'author_loop_done', novel_id: 'novel-A' }))
    expect(state.byNovelId['novel-A'].author).toBe(true)

    state = viewUnreadReducer(state, viewFocusChanged({ novelId: 'novel-A', view: 'author', isArchives: false }))
    expect(state.byNovelId['novel-A'].author).toBe(false)
  })

  it('ignores events without a novel_id', () => {
    const state = viewUnreadReducer(undefined, wsEventReceived({ type: 'author_loop_done' }))
    expect(state.byNovelId).toEqual({})
  })

  it('selector defaults to the empty state for a novel with no activity', () => {
    const rootState = { viewUnread: viewUnreadReducer(undefined, { type: '@@init' }) } as RootState
    expect(selectViewUnreadForNovel('novel-Z')(rootState)).toEqual({
      author: false, chat: false, sandbox: false, archives: false,
    })
  })
})
