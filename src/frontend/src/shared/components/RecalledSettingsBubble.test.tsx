import React from 'react'
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { RecalledSettingsBubble } from './RecalledSettingsBubble'

afterEach(() => cleanup())

describe('RecalledSettingsBubble', () => {
  it('命中为空时返回 null（不渲染任何内容，与 RecallContextBubble 不同）', () => {
    const { container } = render(<RecalledSettingsBubble recalledSettings={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('命中非空时渲染折叠块标题带计数', () => {
    render(
      <RecalledSettingsBubble
        recalledSettings={[
          { category: 'power_system', name: '元气', desc: '气血流动力量' },
        ]}
      />,
    )
    expect(screen.getByText('📚 设定回收 (1)')).toBeTruthy()
  })

  it('展开后每条显示分类标签 + name + desc', () => {
    render(
      <RecalledSettingsBubble
        forceOpen
        recalledSettings={[
          { category: 'power_system', name: '元气', desc: '气血流动力量' },
          { category: 'factions', name: '门派A', desc: '大陆第一门派' },
        ]}
      />,
    )
    expect(screen.getByText('📚 设定回收 (2)')).toBeTruthy()
    expect(screen.getByText('[力量体系]')).toBeTruthy()
    expect(screen.getByText(/元气/)).toBeTruthy()
    expect(screen.getByText(/气血流动力量/)).toBeTruthy()
    expect(screen.getByText('[势力]')).toBeTruthy()
    expect(screen.getByText(/门派A/)).toBeTruthy()
  })

  it('未知 category 兜底显示原始 key，不崩溃', () => {
    render(
      <RecalledSettingsBubble
        forceOpen
        recalledSettings={[{ category: 'unknown_key', name: '测试', desc: '测试描述' }]}
      />,
    )
    expect(screen.getByText('[unknown_key]')).toBeTruthy()
  })

  it('默认折叠（forceOpen 未传时不展开）', () => {
    render(
      <RecalledSettingsBubble
        recalledSettings={[{ category: 'power_system', name: '元气', desc: '气血流动力量' }]}
      />,
    )
    expect(screen.getByText('📚 设定回收 (1)').closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('closed')
  })
})
