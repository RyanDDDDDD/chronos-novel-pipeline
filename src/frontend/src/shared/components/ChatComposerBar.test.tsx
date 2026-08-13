import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import ChatComposerBar from '@/shared/components/ChatComposerBar'

beforeEach(() => cleanup())

describe('ChatComposerBar', () => {
  it('busy=false renders a Send button that calls onSubmit', () => {
    const onSubmit = vi.fn()
    const onCancel = vi.fn()
    render(
      <ChatComposerBar value="x" onChange={vi.fn()} onSubmit={onSubmit} onCancel={onCancel} busy={false} />,
    )
    fireEvent.click(screen.getByLabelText('发送'))
    expect(onSubmit).toHaveBeenCalled()
  })

  it('busy=true renders a red cancel button that calls onCancel, not onSubmit', () => {
    const onSubmit = vi.fn()
    const onCancel = vi.fn()
    render(
      <ChatComposerBar value="x" onChange={vi.fn()} onSubmit={onSubmit} onCancel={onCancel} busy />,
    )
    const btn = screen.getByLabelText('中断')
    expect(btn.getAttribute('data-variant')).toBe('destructive')
    fireEvent.click(btn)
    expect(onCancel).toHaveBeenCalled()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('Escape triggers onCancel while busy', () => {
    const onCancel = vi.fn()
    render(
      <ChatComposerBar value="" onChange={vi.fn()} onSubmit={vi.fn()} onCancel={onCancel} busy />,
    )
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onCancel).toHaveBeenCalled()
  })

  it('Escape does nothing while not busy', () => {
    const onCancel = vi.fn()
    render(
      <ChatComposerBar value="" onChange={vi.fn()} onSubmit={vi.fn()} onCancel={onCancel} busy={false} />,
    )
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('cancelling=true disables the cancel button', () => {
    render(
      <ChatComposerBar
        value="" onChange={vi.fn()} onSubmit={vi.fn()} onCancel={vi.fn()} busy cancelling
      />,
    )
    expect((screen.getByLabelText('中断') as HTMLButtonElement).disabled).toBe(true)
  })

  it('passes onKeyDown through to the inner textarea without swallowing it', () => {
    const onKeyDown = vi.fn()
    render(
      <ChatComposerBar
        value="" onChange={vi.fn()} onSubmit={vi.fn()} onCancel={vi.fn()} busy={false}
        onKeyDown={onKeyDown}
      />,
    )
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'ArrowDown' })
    expect(onKeyDown).toHaveBeenCalled()
  })

  it('mentionCandidates 透传给内部 ChatComposerInput（打 @ 出现下拉）', () => {
    render(
      <ChatComposerBar
        value="@小" onChange={vi.fn()} onSubmit={vi.fn()} onCancel={vi.fn()} busy={false}
        mentionCandidates={[{ name: '小明', type: 'character' }]}
      />,
    )
    const el = screen.getByRole('textbox') as HTMLTextAreaElement
    el.setSelectionRange(2, 2)
    fireEvent.select(el)
    expect(screen.getByRole('listbox')).toBeTruthy()
  })
})
