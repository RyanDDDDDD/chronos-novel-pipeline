/** @vitest-environment jsdom */
import { describe, it, expect, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useComposerHistory } from './useComposerHistory'

function fakeEvent(
  key: 'ArrowUp' | 'ArrowDown' | 'a',
  selectionStart: number,
  selectionEnd = selectionStart,
): React.KeyboardEvent<HTMLTextAreaElement> {
  return {
    key,
    preventDefault: vi.fn(),
    currentTarget: { selectionStart, selectionEnd },
  } as unknown as React.KeyboardEvent<HTMLTextAreaElement>
}

describe('useComposerHistory', () => {
  it('空输入按 ↑ 加载最新一条，连续按 ↑ 逐条更早，到最早一条后不再变化', () => {
    const { result } = renderHook(() => useComposerHistory(['第一条', '第二条', '第三条']))
    const onChange = vi.fn()

    expect(result.current.handleKey(fakeEvent('ArrowUp', 0), '', onChange)).toBe(true)
    expect(onChange).toHaveBeenLastCalledWith('第三条')

    expect(result.current.handleKey(fakeEvent('ArrowUp', 3), '第三条', onChange)).toBe(true)
    expect(onChange).toHaveBeenLastCalledWith('第二条')

    expect(result.current.handleKey(fakeEvent('ArrowUp', 3), '第二条', onChange)).toBe(true)
    expect(onChange).toHaveBeenLastCalledWith('第一条')

    // 已经在最早一条，再按 ↑ 仍然"处理了"这次按键（吞掉默认光标移动），但值不再变化
    onChange.mockClear()
    expect(result.current.handleKey(fakeEvent('ArrowUp', 3), '第一条', onChange)).toBe(true)
    expect(onChange).toHaveBeenLastCalledWith('第一条')
  })

  it('翻到某条后按 ↓ 逐条更新，翻过最新一条后恢复最初草稿（含草稿为空字符串）', () => {
    const { result } = renderHook(() => useComposerHistory(['第一条', '第二条']))
    const onChange = vi.fn()

    result.current.handleKey(fakeEvent('ArrowUp', 0), '', onChange) // -> 第二条
    result.current.handleKey(fakeEvent('ArrowUp', 3), '第二条', onChange) // -> 第一条

    expect(result.current.handleKey(fakeEvent('ArrowDown', 0), '第一条', onChange)).toBe(true)
    expect(onChange).toHaveBeenLastCalledWith('第二条')

    expect(result.current.handleKey(fakeEvent('ArrowDown', 3), '第二条', onChange)).toBe(true)
    expect(onChange).toHaveBeenLastCalledWith('') // 恢复最初的空草稿
  })

  it('草稿非空时也能正确恢复', () => {
    const { result } = renderHook(() => useComposerHistory(['唯一历史']))
    const onChange = vi.fn()

    result.current.handleKey(fakeEvent('ArrowUp', 6), '写到一半', onChange)
    expect(onChange).toHaveBeenLastCalledWith('唯一历史')

    result.current.handleKey(fakeEvent('ArrowDown', 4), '唯一历史', onChange)
    expect(onChange).toHaveBeenLastCalledWith('写到一半')
  })

  it('光标在多行文本中间（前后都有换行）时 Up/Down 不拦截', () => {
    const { result } = renderHook(() => useComposerHistory(['历史']))
    const onChange = vi.fn()
    const value = '第一行\n第二行\n第三行'
    const midOfSecondLine = value.indexOf('二行')

    expect(result.current.handleKey(fakeEvent('ArrowUp', midOfSecondLine), value, onChange)).toBe(false)
    expect(result.current.handleKey(fakeEvent('ArrowDown', midOfSecondLine), value, onChange)).toBe(false)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('历史为空时 Up/Down 不拦截', () => {
    const { result } = renderHook(() => useComposerHistory([]))
    const onChange = vi.fn()
    expect(result.current.handleKey(fakeEvent('ArrowUp', 0), '', onChange)).toBe(false)
    expect(result.current.handleKey(fakeEvent('ArrowDown', 0), '', onChange)).toBe(false)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('翻历史后手动改了内容再按 ↑，以新内容为草稿重新从最新一条开始', () => {
    const { result } = renderHook(() => useComposerHistory(['第一条', '第二条']))
    const onChange = vi.fn()

    result.current.handleKey(fakeEvent('ArrowUp', 0), '', onChange) // -> 第二条
    // 用户在"第二条"基础上手动编辑成了别的内容，value 不再等于 hook 上次写入的值
    result.current.handleKey(fakeEvent('ArrowUp', 2), '改过的草稿', onChange)
    expect(onChange).toHaveBeenLastCalledWith('第二条') // 重新从最新一条开始，不是继续往回翻

    result.current.handleKey(fakeEvent('ArrowDown', 3), '第二条', onChange)
    expect(onChange).toHaveBeenLastCalledWith('改过的草稿') // 草稿被更新为编辑后的内容
  })

  it('entries 引用变化（切 branch/清空对话）后翻页状态重置', () => {
    const { result, rerender } = renderHook(
      ({ entries }: { entries: string[] }) => useComposerHistory(entries),
      { initialProps: { entries: ['旧历史A', '旧历史B'] } },
    )
    const onChange = vi.fn()
    result.current.handleKey(fakeEvent('ArrowUp', 0), '', onChange) // -> 旧历史B

    rerender({ entries: [] })
    // 新 entries 为空，即使 hook 内部索引没清也应该表现为"没有历史"
    expect(result.current.handleKey(fakeEvent('ArrowUp', 4), '旧历史B', onChange)).toBe(false)
  })
})
