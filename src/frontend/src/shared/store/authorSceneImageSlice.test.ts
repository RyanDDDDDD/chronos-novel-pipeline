import { describe, it, expect } from 'vitest'
import reducer, {
  selectAuthorSceneImageStatus, selectAuthorSceneImageLastFailure,
} from './authorSceneImageSlice'
import { wsEventReceived } from '@/shared/store/wsActions'

describe('authorSceneImageSlice', () => {
  it('marks generating on started, clears on done', () => {
    let s = reducer(undefined, wsEventReceived({
      type: 'author_scene_image_started', novel_id: 'n', chapter: 6, index: 2,
    } as never))
    expect(selectAuthorSceneImageStatus({ authorSceneImage: s } as never, 6, 2)).toBe('generating')
    s = reducer(s, wsEventReceived({
      type: 'author_scene_image_done', novel_id: 'n', chapter: 6, index: 2, filename: 'x.png',
    } as never))
    expect(selectAuthorSceneImageStatus({ authorSceneImage: s } as never, 6, 2)).toBeUndefined()
  })

  it('marks failed + records lastFailure on done+error', () => {
    let s = reducer(undefined, wsEventReceived({
      type: 'author_scene_image_started', novel_id: 'n', chapter: 6, index: 2,
    } as never))
    s = reducer(s, wsEventReceived({
      type: 'author_scene_image_done', novel_id: 'n', chapter: 6, index: 2, error: '未配置模型',
    } as never))
    expect(selectAuthorSceneImageStatus({ authorSceneImage: s } as never, 6, 2)).toBe('failed')
    expect(selectAuthorSceneImageLastFailure({ authorSceneImage: s } as never)).toEqual({ chapter: 6, index: 2, error: '未配置模型' })
  })

  it('ignores events missing chapter / index', () => {
    const s = reducer(undefined, wsEventReceived({
      type: 'author_scene_image_started', novel_id: 'n',
    } as never))
    expect(s.byKey).toEqual({})
  })

  it('drops a restarted chapter\'s statuses + failure on author_loop_start', () => {
    let s = reducer(undefined, wsEventReceived({
      type: 'author_scene_image_started', novel_id: 'n', chapter: 6, index: 2,
    } as never))
    s = reducer(s, wsEventReceived({
      type: 'author_scene_image_done', novel_id: 'n', chapter: 6, index: 2, error: 'boom',
    } as never))
    s = reducer(s, wsEventReceived({
      type: 'author_scene_image_started', novel_id: 'n', chapter: 7, index: 0,
    } as never))

    s = reducer(s, wsEventReceived({ type: 'author_loop_start', chapter: 6 } as never))

    expect(selectAuthorSceneImageStatus({ authorSceneImage: s } as never, 6, 2)).toBeUndefined()
    expect(selectAuthorSceneImageStatus({ authorSceneImage: s } as never, 7, 0)).toBe('generating')
    expect(selectAuthorSceneImageLastFailure({ authorSceneImage: s } as never)).toBeNull()
  })

  it('keeps a chapter\'s statuses when that chapter is only resumed', () => {
    let s = reducer(undefined, wsEventReceived({
      type: 'author_scene_image_started', novel_id: 'n', chapter: 6, index: 2,
    } as never))

    s = reducer(s, wsEventReceived({ type: 'author_loop_start', chapter: 6, resume: true } as never))

    expect(selectAuthorSceneImageStatus({ authorSceneImage: s } as never, 6, 2)).toBe('generating')
  })

  it('keeps another chapter\'s failure when a different chapter restarts', () => {
    let s = reducer(undefined, wsEventReceived({
      type: 'author_scene_image_done', novel_id: 'n', chapter: 6, index: 2, error: 'boom',
    } as never))

    s = reducer(s, wsEventReceived({ type: 'author_loop_start', chapter: 7 } as never))

    expect(selectAuthorSceneImageStatus({ authorSceneImage: s } as never, 6, 2)).toBe('failed')
    expect(selectAuthorSceneImageLastFailure({ authorSceneImage: s } as never)).toEqual({ chapter: 6, index: 2, error: 'boom' })
  })
})
