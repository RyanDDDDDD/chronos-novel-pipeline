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
    expect(selectAuthorSceneImageLastFailure({ authorSceneImage: s } as never)).toEqual({ index: 2, error: '未配置模型' })
  })

  it('ignores events missing chapter / index', () => {
    const s = reducer(undefined, wsEventReceived({
      type: 'author_scene_image_started', novel_id: 'n',
    } as never))
    expect(s.byKey).toEqual({})
  })
})
