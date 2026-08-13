import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react'
import ModelRadioList from '@/shared/components/ModelRadioList'

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('ModelRadioList onSearchMiss', () => {
  it('calls onSearchMiss once after the debounce window when the filtered result is empty', async () => {
    const onSearchMiss = vi.fn()
    render(
      <ModelRadioList
        models={['aaa.safetensors', 'bbb.safetensors']}
        name="test-models"
        selected={undefined}
        onSelect={vi.fn()}
        onSearchMiss={onSearchMiss}
      />,
    )

    fireEvent.change(screen.getByLabelText('搜索模型'), { target: { value: 'zzz-no-match' } })
    expect(onSearchMiss).not.toHaveBeenCalled()

    await act(async () => {
      vi.advanceTimersByTime(400)
    })

    expect(onSearchMiss).toHaveBeenCalledTimes(1)
  })

  it('does not call onSearchMiss when there are matches', async () => {
    const onSearchMiss = vi.fn()
    render(
      <ModelRadioList
        models={['aaa.safetensors', 'bbb.safetensors']}
        name="test-models"
        selected={undefined}
        onSelect={vi.fn()}
        onSearchMiss={onSearchMiss}
      />,
    )

    fireEvent.change(screen.getByLabelText('搜索模型'), { target: { value: 'aaa' } })
    await act(async () => {
      vi.advanceTimersByTime(400)
    })

    expect(onSearchMiss).not.toHaveBeenCalled()
  })

  it('does not throw when onSearchMiss is not provided', async () => {
    render(
      <ModelRadioList
        models={['aaa.safetensors']}
        name="test-models"
        selected={undefined}
        onSelect={vi.fn()}
      />,
    )

    fireEvent.change(screen.getByLabelText('搜索模型'), { target: { value: 'zzz-no-match' } })
    await act(async () => {
      vi.advanceTimersByTime(400)
    })
    // no assertion needed beyond "did not throw"
  })
})
