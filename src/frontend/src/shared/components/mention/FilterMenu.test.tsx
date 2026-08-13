import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { FilterMenu } from './FilterMenu'

afterEach(() => cleanup())

describe('FilterMenu', () => {
  it('open=false 时不渲染菜单内容', () => {
    render(
      <FilterMenu
        open={false}
        items={[{ id: 'a', label: 'Item A' }]}
        onSelect={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    )
    expect(screen.queryByText('Item A')).toBeNull()
  })

  it('items 为空时显示 emptyText', () => {
    render(
      <FilterMenu
        open
        items={[]}
        onSelect={vi.fn()}
        onOpenChange={vi.fn()}
        emptyText="无匹配项"
      />,
    )
    expect(screen.getByText('无匹配项')).toBeTruthy()
  })

  it('点击 CommandItem 触发 onSelect(item.id)', () => {
    const onSelect = vi.fn()
    render(
      <FilterMenu
        open
        items={[{ id: 'foo', label: '/foo', sublabel: 'desc' }]}
        onSelect={onSelect}
        onOpenChange={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByText('/foo'))
    expect(onSelect).toHaveBeenCalledWith('foo')
  })

  it('highlightedId 对应项有高亮 className', () => {
    render(
      <FilterMenu
        open
        items={[
          { id: 'a', label: 'A' },
          { id: 'b', label: 'B' },
        ]}
        highlightedId="b"
        onSelect={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    )
    const highlighted = screen.getByText('B').closest('[data-slot="command-item"]')
    expect(highlighted?.className).toContain('bg-[var(--c-accent-subtle)]')
  })
})
