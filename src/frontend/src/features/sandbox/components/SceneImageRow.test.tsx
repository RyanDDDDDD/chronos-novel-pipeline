import React from 'react'
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { Provider } from 'react-redux'
import { configureStore } from '@reduxjs/toolkit'
import sandboxSceneImage from '@/shared/store/sandboxSceneImageSlice'
import SceneImageRow from '@/features/sandbox/components/SceneImageRow'

afterEach(() => {
  cleanup()
})

function wrap(ui: React.ReactElement) {
  const store = configureStore({ reducer: { sandboxSceneImage } })
  return render(<Provider store={store}>{ui}</Provider>)
}

describe('SceneImageRow', () => {
  it('shows a generate button when no image yet', () => {
    const onGenerate = vi.fn()
    wrap(
      <SceneImageRow chapter={3} branchId="b1" roundId="r1" imageUrl={undefined} onGenerate={onGenerate} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /生图/ }))
    expect(onGenerate).toHaveBeenCalled()
  })

  it('renders the image + a regenerate button when imageUrl is set', () => {
    wrap(
      <SceneImageRow chapter={3} branchId="b1" roundId="r1" imageUrl="/x.png?v=1" onGenerate={vi.fn()} />,
    )
    expect(screen.getByRole('img').getAttribute('src')).toBe('/x.png?v=1')
    expect(screen.getByRole('button', { name: /重新生成/ })).toBeTruthy()
  })
})
