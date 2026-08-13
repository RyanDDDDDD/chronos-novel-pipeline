import { describe, expect, it } from 'vitest'
import { computeSkeletonCharCounts } from '@/features/setup/utils/skeleton'

describe('computeSkeletonCharCounts', () => {
  it('counts outline and beats per stage and totals', () => {
    const counts = computeSkeletonCharCounts([
      {
        stage_num: 1,
        description: '甲乙 对峙',
        beats: [{ text: '拍一' }, { text: '拍 二' }],
        expanded: true,
      },
      {
        stage_num: 2,
        description: '丙登场',
        beats: [],
        expanded: false,
      },
    ])
    expect(counts.stages).toEqual([
      { stage_num: 1, outline: 4, beats: 4 },
      { stage_num: 2, outline: 3, beats: 0 },
    ])
    expect(counts.outlineTotal).toBe(7)
    expect(counts.beatsTotal).toBe(4)
  })
})
