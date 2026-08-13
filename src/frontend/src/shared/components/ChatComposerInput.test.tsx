import React from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ChatComposerInput from '@/shared/components/ChatComposerInput'

afterEach(() => {
  cleanup()
})

describe('ChatComposerInput', () => {
  it('default mode includes border chrome', () => {
    render(
      <ChatComposerInput value="" onChange={() => {}} onSubmit={() => {}} />,
    )
    const el = screen.getByRole('textbox')
    expect(el.className).toContain('border')
    expect(el.className).toContain('bg-white')
  })

  it('bare mode omits composer chrome classes from shadcn Textarea defaults', () => {
    render(
      <ChatComposerInput bare value="" onChange={() => {}} onSubmit={() => {}} />,
    )
    const el = screen.getByRole('textbox')
    expect(el.className).not.toContain('border-slate-300')
    expect(el.className).not.toContain('bg-white')
    expect(el.className).not.toContain('shadow-sm')
    expect(el.className).not.toContain('disabled:bg-slate-100')
  })

  it('forwards ref to the underlying textarea', () => {
    const ref = React.createRef<HTMLTextAreaElement>()
    render(
      <ChatComposerInput ref={ref} value="" onChange={() => {}} onSubmit={() => {}} />,
    )
    expect(ref.current).toBe(screen.getByRole('textbox'))
  })

  describe('mentionCandidates', () => {
    it('不传 mentionCandidates 时，打 @ 不出现下拉（回归：不影响原有行为）', () => {
      render(
        <ChatComposerInput value="@" onChange={() => {}} onSubmit={() => {}} />,
      )
      expect(screen.queryByRole('listbox')).toBeNull()
    })

    it('传入 mentionCandidates 后，光标在 @ 片段中会出现候选下拉', () => {
      const onChange = vi.fn()
      render(
        <ChatComposerInput
          value="@小" onChange={onChange} onSubmit={() => {}}
          mentionCandidates={[{ name: '小明', type: 'character' }, { name: '小红', type: 'character' }]}
        />,
      )
      const el = screen.getByRole('textbox') as HTMLTextAreaElement
      el.setSelectionRange(2, 2)
      fireEvent.select(el)
      expect(screen.getByRole('listbox')).toBeTruthy()
      expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['小明 [角色]', '小红 [角色]'])
    })

    it('方向键切换选中项，Enter 插入选中的候选并关闭下拉', () => {
      let value = '@小'
      const onChange = vi.fn((v: string) => { value = v })
      const { rerender } = render(
        <ChatComposerInput
          value={value} onChange={onChange} onSubmit={() => {}}
          mentionCandidates={[{ name: '小明', type: 'character' }, { name: '小红', type: 'character' }]}
        />,
      )
      const el = screen.getByRole('textbox') as HTMLTextAreaElement
      el.setSelectionRange(2, 2)
      fireEvent.select(el)
      fireEvent.keyDown(el, { key: 'ArrowDown' })
      expect(screen.getAllByRole('option')[1].getAttribute('aria-selected')).toBe('true')
      fireEvent.keyDown(el, { key: 'Enter' })
      expect(onChange).toHaveBeenLastCalledWith('@小红 ')
      rerender(
        <ChatComposerInput
          value={value} onChange={onChange} onSubmit={() => {}}
          mentionCandidates={[{ name: '小明', type: 'character' }, { name: '小红', type: 'character' }]}
        />,
      )
      expect(screen.queryByRole('listbox')).toBeNull()
    })

    it('Escape 关闭下拉但不改动文本', () => {
      const onChange = vi.fn()
      render(
        <ChatComposerInput
          value="@小" onChange={onChange} onSubmit={() => {}}
          mentionCandidates={[{ name: '小明', type: 'character' }, { name: '小红', type: 'character' }]}
        />,
      )
      const el = screen.getByRole('textbox') as HTMLTextAreaElement
      el.setSelectionRange(2, 2)
      fireEvent.select(el)
      expect(screen.getByRole('listbox')).toBeTruthy()
      fireEvent.keyDown(el, { key: 'Escape' })
      expect(screen.queryByRole('listbox')).toBeNull()
      expect(onChange).not.toHaveBeenCalled()
    })

    it('点击候选项触发 onChange 插入 "@全名 "', () => {
      let value = '@小'
      const onChange = vi.fn((v: string) => { value = v })
      render(
        <ChatComposerInput
          value={value} onChange={onChange} onSubmit={() => {}}
          mentionCandidates={[{ name: '小明', type: 'character' }, { name: '小红', type: 'character' }]}
        />,
      )
      const el = screen.getByRole('textbox') as HTMLTextAreaElement
      el.setSelectionRange(2, 2)
      fireEvent.select(el)
      const item = screen.getByText('小明')
      fireEvent.mouseDown(item)
      fireEvent.click(item)
      expect(onChange).toHaveBeenCalledWith('@小明 ')
    })
  })
})
