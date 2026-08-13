import React from 'react'
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import MentionDropdown from './MentionDropdown'
import type { MentionCandidate } from './mentionCandidates'

function makeCandidates(n: number): MentionCandidate[] {
  return Array.from({ length: n }, (_, i) => ({ name: `候选${i}`, type: 'character' }) as const)
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

afterEach(() => cleanup())

describe('MentionDropdown', () => {
  it('candidates 为空数组时不渲染任何内容', () => {
    const { container } = render(
      <MentionDropdown candidates={[]} selectedIndex={0} onSelect={vi.fn()} onDismiss={vi.fn()} />,
    )
    expect(container.querySelector('[data-slot="popover-content"]')).toBeNull()
  })

  it('渲染每个候选名+类型标签，selectedIndex 对应项标记为选中', () => {
    const candidates: MentionCandidate[] = [
      { name: '橘花音', type: 'character' },
      { name: '苏晚晴', type: 'setting' },
    ]
    render(
      <MentionDropdown candidates={candidates} selectedIndex={1} onSelect={vi.fn()} onDismiss={vi.fn()} />,
    )
    expect(screen.getByText('橘花音')).toBeTruthy()
    expect(screen.getByText('苏晚晴')).toBeTruthy()
    expect(screen.getByText('角色')).toBeTruthy()
    expect(screen.getByText('设定')).toBeTruthy()
    const highlighted = screen.getByText('苏晚晴').closest('[data-slot="command-item"]')
    expect(highlighted?.className).toContain('bg-[var(--c-accent-subtle)]')
  })

  it('点击候选项触发 onSelect，传回纯名字（不带类型标签）', () => {
    const onSelect = vi.fn()
    const candidates: MentionCandidate[] = [
      { name: '橘花音', type: 'character' },
      { name: '苏晚晴', type: 'character' },
    ]
    render(
      <MentionDropdown candidates={candidates} selectedIndex={0} onSelect={onSelect} onDismiss={vi.fn()} />,
    )
    fireEvent.mouseDown(screen.getByText('苏晚晴'))
    fireEvent.click(screen.getByText('苏晚晴'))
    expect(onSelect).toHaveBeenCalledWith('苏晚晴')
  })

  it('点击候选项前的 mousedown 不会把焦点从触发输入框移走导致 Popover 提前关闭', () => {
    // Regression: cmdk items are plain (non-focusable) divs. Without preventing the
    // mousedown's default focus-shift, focus falls back to <body>, which Radix's
    // DismissableLayer reads as "focus left the popover" and dismisses it before the
    // click's own onSelect(id) can run — a race that only sometimes loses.
    const onSelect = vi.fn()
    const onDismiss = vi.fn()
    const candidates: MentionCandidate[] = [{ name: '橘花音', type: 'character' }]
    render(
      <MentionDropdown candidates={candidates} selectedIndex={0} onSelect={onSelect} onDismiss={onDismiss} />,
    )
    const item = screen.getByText('橘花音')
    const mouseDownEvent = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
    const prevented = !item.dispatchEvent(mouseDownEvent)
    expect(prevented).toBe(true)
    fireEvent.click(item)
    expect(onSelect).toHaveBeenCalledWith('橘花音')
    expect(onDismiss).not.toHaveBeenCalled()
  })

  it('highlightedId 随 selectedIndex 变化更新高亮项，并滚动进可视区域', () => {
    const candidates = makeCandidates(20)
    const { rerender } = render(
      <MentionDropdown candidates={candidates} selectedIndex={0} onSelect={vi.fn()} onDismiss={vi.fn()} />,
    )
    const firstHighlighted = screen.getByText('候选0').closest('[data-slot="command-item"]')
    expect(firstHighlighted?.className).toContain('bg-[var(--c-accent-subtle)]')

    const scrollSpy = vi.fn()
    Element.prototype.scrollIntoView = scrollSpy

    rerender(
      <MentionDropdown candidates={candidates} selectedIndex={10} onSelect={vi.fn()} onDismiss={vi.fn()} />,
    )
    const nextHighlighted = screen.getByText('候选10').closest('[data-slot="command-item"]')
    expect(nextHighlighted?.className).toContain('bg-[var(--c-accent-subtle)]')
    expect(scrollSpy).toHaveBeenCalledWith({ block: 'nearest' })
  })

  it('Popover 自行关闭（非选中）时调用 onDismiss，而非用空字符串触发 onSelect', () => {
    const onSelect = vi.fn()
    const onDismiss = vi.fn()
    const candidates: MentionCandidate[] = [{ name: '橘花音', type: 'character' }]
    render(
      <MentionDropdown candidates={candidates} selectedIndex={0} onSelect={onSelect} onDismiss={onDismiss} />,
    )
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onDismiss).toHaveBeenCalled()
    expect(onSelect).not.toHaveBeenCalled()
  })
})
