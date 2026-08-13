import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react'
import CopyButton from '@/shared/components/CopyButton'

beforeEach(() => {
  cleanup()
  vi.useFakeTimers()
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('CopyButton', () => {
  it('copies the given text to the clipboard on click', async () => {
    render(<CopyButton text="hello world" />)
    await fireEvent.click(screen.getByRole('button'))
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('hello world')
  })

  it('swaps to a checked state after copying, then reverts', async () => {
    render(<CopyButton text="x" />)
    const btn = screen.getByRole('button', { name: '复制' })
    await act(async () => {
      fireEvent.click(btn)
      await Promise.resolve()
    })
    expect(screen.getByRole('button', { name: '已复制' })).toBeTruthy()
    await act(async () => {
      vi.advanceTimersByTime(1500)
    })
    expect(screen.getByRole('button', { name: '复制' })).toBeTruthy()
  })

  it('does not propagate the click to ancestor handlers', async () => {
    const onAncestorClick = vi.fn()
    render(
      <div onClick={onAncestorClick}>
        <CopyButton text="x" />
      </div>,
    )
    await fireEvent.click(screen.getByRole('button'))
    expect(onAncestorClick).not.toHaveBeenCalled()
  })
})
