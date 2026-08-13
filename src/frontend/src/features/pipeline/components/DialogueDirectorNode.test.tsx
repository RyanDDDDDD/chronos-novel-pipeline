import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { screen, cleanup } from '@testing-library/react'
import { render } from '@testing-library/react'
import DialogueDirectorNode from '@/features/pipeline/components/DialogueDirectorNode'
import { renderWithClient } from '@/test/renderWithClient'

vi.mock('@xyflow/react', () => ({
  Handle: () => null,
  Position: { Left: 'left', Right: 'right' },
}))

afterEach(() => cleanup())

describe('DialogueDirectorNode', () => {
  it('只渲染标签和"点击节点配置采样参数"提示，不再读写 dialogue config', () => {
    renderWithClient(<DialogueDirectorNode data={{ label: '导演' }} />)
    expect(screen.getByText('导演')).toBeTruthy()
    expect(screen.getByText('点击节点配置采样参数')).toBeTruthy()
    expect(screen.queryByRole('checkbox')).toBeNull()
  })

  it('selected 为 true 时外层容器带高亮 ring 样式', () => {
    const { container } = render(<DialogueDirectorNode data={{ label: '导演', selected: true }} />)
    expect(container.querySelector('.ring-2')).toBeTruthy()
  })

  it('data.hint 存在时覆盖默认提示（供对话agent等非采样参数节点复用同一视觉样式）', () => {
    renderWithClient(<DialogueDirectorNode data={{ label: '对话agent', hint: '点击节点配置身份设定' }} />)
    expect(screen.getByText('对话agent')).toBeTruthy()
    expect(screen.getByText('点击节点配置身份设定')).toBeTruthy()
    expect(screen.queryByText('点击节点配置采样参数')).toBeNull()
  })
})
