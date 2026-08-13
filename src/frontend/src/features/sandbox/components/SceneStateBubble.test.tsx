import React from 'react'
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { SceneStateBubble } from './SceneStateBubble'

afterEach(() => {
  cleanup()
})

describe('SceneStateBubble', () => {
  it('renders nothing when scene is empty', () => {
    const { container } = render(<SceneStateBubble scene={{}} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders only the non-empty fields, in fixed order', () => {
    render(
      <SceneStateBubble scene={{
        description: '昏暗的储物间', objects: '纸箱散落一地', atmosphere: '', disruption: '门被反锁',
      }} />,
    )
    fireEvent.click(screen.getByText(/🏛️ 场景状态（推演）/))
    expect(screen.getByText(/环境：昏暗的储物间/)).toBeTruthy()
    expect(screen.getByText(/物件：纸箱散落一地/)).toBeTruthy()
    expect(screen.getByText(/异常：门被反锁/)).toBeTruthy()
    expect(screen.queryByText(/氛围：/)).toBeNull()
  })

  it('defaults to collapsed when entry is not set, expanded when entry is true', () => {
    const { rerender } = render(<SceneStateBubble scene={{ description: '书房' }} />)
    expect(screen.getByText(/🏛️ 场景状态（推演）/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('closed')
    rerender(<SceneStateBubble scene={{ description: '书房' }} entry />)
    expect(screen.getByText(/🏛️ 场景进入态（初始）/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('open')
  })

  it('forceOpen overrides the entry-based default in both directions', () => {
    const { rerender } = render(<SceneStateBubble scene={{ description: '书房' }} forceOpen />)
    expect(screen.getByText(/🏛️ 场景状态（推演）/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('open')
    rerender(<SceneStateBubble scene={{ description: '书房' }} entry forceOpen={false} />)
    expect(screen.getByText(/🏛️ 场景进入态（初始）/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('closed')
  })

  it('supports overriding the title', () => {
    render(<SceneStateBubble scene={{ description: '书房' }} title="🌱 开场初始场景" />)
    expect(screen.getByText(/🌱 开场初始场景/)).toBeTruthy()
  })
})
