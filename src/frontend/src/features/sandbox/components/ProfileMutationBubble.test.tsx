import React from 'react'
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { ProfileMutationBubble } from './ProfileMutationBubble'

afterEach(() => {
  cleanup()
})

describe('ProfileMutationBubble', () => {
  it('renders scalar fields as label:value', () => {
    render(<ProfileMutationBubble mutation={{ 甲: { race: '精灵', gender: 'xeno' } }} />)
    expect(screen.getByText(/种族：精灵/)).toBeTruthy()
    expect(screen.getByText(/性别：xeno/)).toBeTruthy()
  })

  it('renders hobbies as a joined list', () => {
    render(<ProfileMutationBubble mutation={{ 甲: { hobbies: ['炼金', '剑术'] } }} />)
    expect(screen.getByText(/爱好：炼金、剑术/)).toBeTruthy()
  })

  it('renders physique as per-slot lines', () => {
    render(<ProfileMutationBubble mutation={{ 甲: { physique: { 面容: '冷峻', 手臂: '有伤疤' } } }} />)
    expect(screen.getByText(/面容：冷峻/)).toBeTruthy()
    expect(screen.getByText(/手臂：有伤疤/)).toBeTruthy()
  })

  it('renders sliders as axis:text lines', () => {
    render(<ProfileMutationBubble mutation={{
      甲: { sliders: { 侵蚀度: { level: 1, text: '开始动摇' } } },
    }} />)
    expect(screen.getByText(/侵蚀度：开始动摇/)).toBeTruthy()
  })

  it('defaults to open', () => {
    render(<ProfileMutationBubble mutation={{ 甲: { race: '精灵' } }} />)
    expect(screen.getByText(/🧬 档案\/关系突变/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('open')
  })

  it('forceOpen overrides the default', () => {
    render(<ProfileMutationBubble mutation={{ 甲: { race: '精灵' } }} forceOpen={false} />)
    expect(screen.getByText(/🧬 档案\/关系突变/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('closed')
  })

  it('joins multiple character names in the summary', () => {
    render(<ProfileMutationBubble mutation={{ 甲: { race: '精灵' }, 乙: { gender: 'xeno' } }} />)
    fireEvent.click(screen.getByText(/🧬 档案\/关系突变/))
    expect(screen.getByText(/甲、乙/)).toBeTruthy()
  })

  it('shows rewrite row when onRewrite is provided', () => {
    render(<ProfileMutationBubble mutation={{ 甲: { race: '精灵' } }} onRewrite={() => {}} />)
    expect(screen.getByPlaceholderText('重写时怎么改（可选）…')).toBeTruthy()
    expect(screen.getByRole('button', { name: '重写突变' })).toBeTruthy()
  })

  it('fires onRewrite on Enter or button click, including empty feedback', () => {
    const onRewrite = vi.fn()
    render(<ProfileMutationBubble mutation={{ 甲: { race: '精灵' } }} onRewrite={onRewrite} />)
    fireEvent.click(screen.getByRole('button', { name: '重写突变' }))
    expect(onRewrite).toHaveBeenCalledWith('')
    const input = screen.getByPlaceholderText('重写时怎么改（可选）…')
    fireEvent.change(input, { target: { value: '改为恶魔' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onRewrite).toHaveBeenCalledWith('改为恶魔')
  })
})
