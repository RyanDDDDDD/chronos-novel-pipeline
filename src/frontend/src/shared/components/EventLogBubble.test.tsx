import React from 'react'
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { EventLogBubble } from './EventLogBubble'

afterEach(() => {
  cleanup()
})

describe('EventLogBubble', () => {
  it('renders nothing when entries is empty', () => {
    const { container } = render(<EventLogBubble entries={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when the only entry has an empty summary', () => {
    const { container } = render(<EventLogBubble entries={[{ summary: '', time: '' }]} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders event and time', () => {
    render(<EventLogBubble entries={[{ summary: '甲把玉佩交给了乙', time: '决战之后' }]} />)
    fireEvent.click(screen.getByText(/🕮 记忆归档/))
    expect(screen.getByText(/事件：甲把玉佩交给了乙/)).toBeTruthy()
    expect(screen.getByText(/时刻：决战之后/)).toBeTruthy()
  })

  it('renders location when present', () => {
    render(
      <EventLogBubble entries={[{ summary: '甲把玉佩交给了乙', time: '', location: '藏经阁' }]} />,
    )
    fireEvent.click(screen.getByText(/🕮 记忆归档/))
    expect(screen.getByText(/地点：藏经阁/)).toBeTruthy()
  })

  it('omits location row when absent', () => {
    render(<EventLogBubble entries={[{ summary: '甲把玉佩交给了乙', time: '' }]} />)
    fireEvent.click(screen.getByText(/🕮 记忆归档/))
    expect(screen.queryByText(/地点：/)).toBeNull()
  })

  it('renders characters when present', () => {
    render(
      <EventLogBubble
        entries={[{ summary: '甲把玉佩交给了乙', time: '', characters: ['甲', '乙'] }]}
      />,
    )
    fireEvent.click(screen.getByText(/🕮 记忆归档/))
    expect(screen.getByText(/人物：甲、乙/)).toBeTruthy()
  })

  it('omits characters row when empty', () => {
    render(<EventLogBubble entries={[{ summary: '甲把玉佩交给了乙', time: '', characters: [] }]} />)
    fireEvent.click(screen.getByText(/🕮 记忆归档/))
    expect(screen.queryByText(/人物：/)).toBeNull()
  })

  it('aggregates multiple entries under a single trigger', () => {
    render(
      <EventLogBubble
        entries={[
          { summary: '甲回忆起童年', time: '闪回' },
          { summary: '乙回忆起师父', time: '闪回' },
        ]}
      />,
    )
    expect(screen.getAllByText(/🕮 记忆归档/)).toHaveLength(1)
    fireEvent.click(screen.getByText(/🕮 记忆归档/))
    expect(screen.getByText(/事件：甲回忆起童年/)).toBeTruthy()
    expect(screen.getByText(/事件：乙回忆起师父/)).toBeTruthy()
  })

  it('skips entries with an empty summary while keeping the rest', () => {
    render(
      <EventLogBubble
        entries={[
          { summary: '', time: '' },
          { summary: '乙回忆起师父', time: '闪回' },
        ]}
      />,
    )
    expect(screen.getAllByText(/🕮 记忆归档/)).toHaveLength(1)
    fireEvent.click(screen.getByText(/🕮 记忆归档/))
    expect(screen.getByText(/事件：乙回忆起师父/)).toBeTruthy()
  })
})
