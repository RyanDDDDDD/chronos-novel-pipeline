import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import SetupChatQueueBar from './SetupChatQueueBar'

describe('SetupChatQueueBar', () => {
  it('renders nothing when the queue is empty', () => {
    const { container } = render(<SetupChatQueueBar items={[]} onRemove={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })

  it('lists queued messages with order badges and remove buttons', () => {
    const onRemove = vi.fn()
    render(
      <SetupChatQueueBar
        items={[
          { id: 'q1', text: '第一条排队', attachmentIds: [] },
          { id: 'q2', text: '第二条排队', attachmentIds: ['a1', 'a2'] },
        ]}
        onRemove={onRemove}
      />,
    )
    const bar = screen.getByTestId('setup-chat-queue-bar')
    expect(bar.className).toContain('absolute')
    expect(bar.className).toContain('bottom-full')
    expect(bar.className).toContain('left-4')
    expect(screen.getByTestId('setup-chat-queue-list').className).toContain('overflow-y-auto')
    expect(screen.getByText('待发送 (2)')).toBeTruthy()
    expect(screen.getByText('第一条排队')).toBeTruthy()
    expect(screen.getByText('第二条排队')).toBeTruthy()
    expect(screen.getByText('2 个附件')).toBeTruthy()
    fireEvent.click(screen.getByLabelText('移出队列：第一条排队'))
    expect(onRemove).toHaveBeenCalledWith('q1')
  })
})
