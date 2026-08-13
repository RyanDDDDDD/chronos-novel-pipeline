import { describe, expect, it } from 'vitest'
import {
  clearViewUnread,
  EMPTY_VIEW_UNREAD,
  markViewUnread,
  viewForWsEventType,
} from '@/shared/utils/viewUnreadBadges'

describe('viewUnreadBadges', () => {
  it('maps WS prefixes to notify views', () => {
    expect(viewForWsEventType('author_loop_token')).toBe('author')
    expect(viewForWsEventType('setup_chat_final')).toBe('chat')
    expect(viewForWsEventType('story_sandbox_done')).toBe('sandbox')
    expect(viewForWsEventType('token_usage')).toBeNull()
  })

  it('maps timeline_cascade_done (only, not _start/_restarted) to the archives tab', () => {
    expect(viewForWsEventType('timeline_cascade_done')).toBe('archives')
    expect(viewForWsEventType('timeline_cascade_started')).toBeNull()
    expect(viewForWsEventType('timeline_cascade_restarted')).toBeNull()
  })

  it('marks unread only when event targets another tab', () => {
    expect(markViewUnread(EMPTY_VIEW_UNREAD, 'author_loop_token', 'chat')).toEqual({
      author: true,
      chat: false,
      sandbox: false,
      archives: false,
    })
    expect(markViewUnread(EMPTY_VIEW_UNREAD, 'setup_chat_token', 'chat')).toBe(EMPTY_VIEW_UNREAD)
  })

  it('marks archives unread on timeline_cascade_done when the user is elsewhere', () => {
    expect(markViewUnread(EMPTY_VIEW_UNREAD, 'timeline_cascade_done', 'pipeline')).toEqual({
      author: false,
      chat: false,
      sandbox: false,
      archives: true,
    })
    expect(markViewUnread(EMPTY_VIEW_UNREAD, 'timeline_cascade_done', 'archives')).toBe(EMPTY_VIEW_UNREAD)
    expect(markViewUnread(EMPTY_VIEW_UNREAD, 'timeline_cascade_done', 'setup', true)).toBe(EMPTY_VIEW_UNREAD)
  })

  it('does not duplicate state when already unread', () => {
    const prev = { author: true, chat: false, sandbox: false, archives: false }
    expect(markViewUnread(prev, 'author_loop_done', 'chat')).toBe(prev)
  })

  it('clears unread for the active tab', () => {
    const prev = { author: true, chat: true, sandbox: false, archives: false }
    expect(clearViewUnread(prev, 'chat')).toEqual({
      author: true,
      chat: false,
      sandbox: false,
      archives: false,
    })
    expect(clearViewUnread(prev, 'author')).toEqual({
      author: false,
      chat: true,
      sandbox: false,
      archives: false,
    })
    expect(clearViewUnread(EMPTY_VIEW_UNREAD, 'chat')).toBe(EMPTY_VIEW_UNREAD)
  })
})
