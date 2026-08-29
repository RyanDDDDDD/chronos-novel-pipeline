import { describe, it, expect } from 'vitest'
import reducer, { selectSceneImageStatus } from '@/shared/store/sandboxSceneImageSlice'
import { wsEventReceived } from '@/shared/store/wsActions'

/* eslint-disable @typescript-eslint/no-explicit-any */

describe('sandboxSceneImageSlice', () => {
  it('marks generating on started, clears on done', () => {
    let s = reducer(undefined, wsEventReceived({
      type: 'sandbox_scene_image_started', novel_id: 'n', chapter: 3, branch_id: 'b1', round_id: 'r1',
    }))
    expect(selectSceneImageStatus({ sandboxSceneImage: s } as any, 3, 'b1', 'r1')).toBe('generating')
    s = reducer(s, wsEventReceived({
      type: 'sandbox_scene_image_done', novel_id: 'n', chapter: 3, branch_id: 'b1', round_id: 'r1',
      filename: 'x.png',
    }))
    expect(selectSceneImageStatus({ sandboxSceneImage: s } as any, 3, 'b1', 'r1')).toBeUndefined()
  })

  it('marks failed + records lastFailure on done+error', () => {
    let s = reducer(undefined, wsEventReceived({
      type: 'sandbox_scene_image_started', novel_id: 'n', chapter: 3, branch_id: 'b1', round_id: 'r1',
    }))
    s = reducer(s, wsEventReceived({
      type: 'sandbox_scene_image_done', novel_id: 'n', chapter: 3, branch_id: 'b1', round_id: 'r1',
      error: '未配置模型',
    }))
    expect(selectSceneImageStatus({ sandboxSceneImage: s } as any, 3, 'b1', 'r1')).toBe('failed')
    expect(s.lastFailure?.error).toBe('未配置模型')
  })

  it('ignores events missing branch_id / round_id', () => {
    const s = reducer(undefined, wsEventReceived({
      type: 'sandbox_scene_image_started', novel_id: 'n', chapter: 3,
    }))
    expect(s.byKey).toEqual({})
  })
})
