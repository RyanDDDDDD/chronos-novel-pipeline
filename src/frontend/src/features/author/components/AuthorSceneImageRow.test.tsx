import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { Provider } from 'react-redux'
import { configureStore } from '@reduxjs/toolkit'
import authorSceneImage from '@/shared/store/authorSceneImageSlice'
import AuthorSceneImageRow from './AuthorSceneImageRow'

afterEach(() => {
  cleanup()
})

const store = (preloaded?: unknown) => configureStore({
  reducer: { authorSceneImage },
  preloadedState: preloaded as never,
})

describe('AuthorSceneImageRow', () => {
  it('shows 生图 button when no image + fires onGenerate', () => {
    const onGenerate = vi.fn()
    render(<Provider store={store()}><AuthorSceneImageRow chapter={6} index={2} onGenerate={onGenerate} /></Provider>)
    fireEvent.click(screen.getByRole('button', { name: /生图/ }))
    expect(onGenerate).toHaveBeenCalled()
  })

  it('shows image + 重新生成 when imageUrl given', () => {
    render(<Provider store={store()}><AuthorSceneImageRow chapter={6} index={2} imageUrl="/x.png" onGenerate={() => {}} /></Provider>)
    expect(screen.getByRole('img').getAttribute('src')).toBe('/x.png')
    expect(screen.getByRole('button', { name: /重新生成/ })).toBeTruthy()
  })

  it('shows 生图中… + disables button while generating', () => {
    render(<Provider store={store({ authorSceneImage: { byKey: { '6:2': 'generating' }, lastFailure: null } })}>
      <AuthorSceneImageRow chapter={6} index={2} onGenerate={() => {}} /></Provider>)
    expect((screen.getByRole('button') as HTMLButtonElement).disabled).toBe(true)
  })
})
