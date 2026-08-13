import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import MechanismStageNode from '@/features/pipeline/components/MechanismStageNode'

vi.mock('@xyflow/react', () => ({
  Handle: () => null,
  Position: { Left: 'left', Right: 'right' },
}))

describe('MechanismStageNode', () => {
  it('selected 为 false/未传时不带高亮样式', () => {
    const { container } = render(<MechanismStageNode data={{ label: '角色状态推演' }} />)
    expect(container.querySelector('.ring-2')).toBeNull()
  })

  it('selected 为 true 时外层容器带高亮 ring 样式', () => {
    const { container } = render(<MechanismStageNode data={{ label: '角色状态推演', selected: true }} />)
    expect(container.querySelector('.ring-2')).toBeTruthy()
  })
})
